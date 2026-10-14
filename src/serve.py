"""
FastAPI 服务：静态站点 + REST API + 每日定时刷新。
本地运行：
  uvicorn src.serve:app --reload --port 8000
  或  python src\\serve.py
"""
import json
import os
import sys
import threading
import datetime
import concurrent.futures as _cf

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from contextlib import asynccontextmanager  # noqa: E402
from typing import Literal  # noqa: E402
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request  # noqa: E402
import time as _time  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field, ConfigDict, field_validator  # noqa: E402

import llm_advice  # noqa: E402  (触发 .env 加载)
import season  # noqa: E402  (统一季节与北京业务日)
import store  # noqa: E402  (SQLite 持久化：上报/传感器)

WEB = os.path.join(ROOT, "web")
DATA_JSON = os.path.join(WEB, "data.json")

_refresh_lock = threading.Lock()
_advice_cache = {}
_ASK_EXEC = _cf.ThreadPoolExecutor(max_workers=4)   # 问答内部超时用


def _season_of(d=None):
    """统一季节策略：由 season.py 决定（Asia/Shanghai 业务日）。"""
    return season.policy(d)["season"]


@asynccontextmanager
async def _lifespan(app):  # noqa: ARG001
    if not os.path.exists(DATA_JSON):
        print("[serve] 首次启动，生成数据 ...")
        _refresh(True)
    # 预加载模型（意图 ONNX + 检索索引），避免首个请求触发冷加载超时
    try:
        from qa import intent_onnx, retriever
        intent_onnx.available()
        if retriever.available():
            retriever._index_vectors()
        print("[serve] 模型预热完成")
    except Exception as e:  # noqa: BLE001
        print("[serve] 模型预热跳过:", e)
    # 若尚无数据版本，启动时落一个初始快照（数据血缘）
    try:
        if store.version_count() == 0 and os.path.exists(DATA_JSON):
            _save_snapshot(note="startup-existing（沿用已有加工数据，非新抓取）")
            print("[serve] 初始数据版本已记录（沿用已有数据）")
    except Exception as e:  # noqa: BLE001
        print("[serve] 初始快照跳过:", e)
    yield


app = FastAPI(title="TeaWindow API", version="1.0",
              description="梅家坞龙井复合气候风险与采摘窗口决策助手",
              lifespan=_lifespan)

# 请求体上限（P0-4：超大 body 在网络/解析前拒绝）
MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", "65536"))
# LLM 每日预算（P0-4：昂贵调用独立配额）
LLM_DAILY_BUDGET = int(os.environ.get("LLM_DAILY_BUDGET", "300"))
_llm_usage = {"date": "", "count": 0}


def _llm_spend():
    today = datetime.date.today().isoformat()
    if _llm_usage["date"] != today:
        _llm_usage["date"], _llm_usage["count"] = today, 0
    if _llm_usage["count"] >= LLM_DAILY_BUDGET:
        return False
    _llm_usage["count"] += 1
    return True


# ---- OpenAPI 响应模型（见评估 §7：200 响应需有 schema）----
class SummaryResp(BaseModel):
    model_config = ConfigDict(extra="allow")
    updated: str
    season: str
    data_age_days: int | None = None
    current: dict | None = None
    next7_max: dict | None = None
    pick_window: list = Field(default_factory=list)
    pick_window_note: str | None = None
    metrics: dict = Field(default_factory=dict)


class AskResp(BaseModel):
    model_config = ConfigDict(extra="allow")
    engine: str = "teawindow-own"
    mode: str | None = None
    intent: str | None = None
    confidence: float | None = None
    backend: str | None = None
    text: str
    chain: list[str] = Field(default_factory=list)
    follow_up: bool = False
    source: str | None = None
    base_text: str | None = None
    note: str | None = None
    format: str | None = None
    state: dict | None = None


def _load():
    if not os.path.exists(DATA_JSON):
        raise HTTPException(503, "数据未就绪，请先运行 pipeline 或调用 /api/refresh")
    with open(DATA_JSON, encoding="utf-8") as f:
        return json.load(f)


def _cur_day(days):
    """今天对应的一天（北京时间）：优先日期==今天；否则最近历史日；否则最后一天。"""
    today = season.iso_today()
    m = [d for d in days if d["date"] == today]
    if m:
        return m[0]
    past = [d for d in days if d["date"] <= today]
    return past[-1] if past else days[-1]


STALE_MINUTES = int(os.environ.get("STALE_MINUTES", "150"))


def _freshness(d=None):
    """数据新鲜度闸门：fetched_at / age_minutes / stale / 刷新状态 / 构建。"""
    try:
        d = d or _load()
        meta = d.get("meta", {}) or {}
        fetched = meta.get("fetched_at") or meta.get("updated")
        try:
            fdt = datetime.datetime.fromisoformat(str(fetched))
            now = season.now()
            if fdt.tzinfo is None:
                now = now.replace(tzinfo=None)
            age = (now - fdt).total_seconds() / 60.0
        except Exception:  # noqa: BLE001
            age = None
    except Exception:  # noqa: BLE001
        fetched, age = None, None
    return {"fetched_at": fetched,
            "age_minutes": None if age is None else round(age, 1),
            "stale": bool(age is not None and age > STALE_MINUTES),
            "stale_threshold_minutes": STALE_MINUTES,
            "build": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:12],
            "refresh": store.get_refresh_state()}


# ---- 简单限流 + 管理令牌（P0-2 / P1-2）----
_RL = {}


def _rate_limit(ip, limit=40, window=60):
    now = _time.time()
    arr = [t for t in _RL.get(ip, []) if now - t < window]
    if len(arr) >= limit:
        raise HTTPException(429, "rate limit exceeded, retry later")
    arr.append(now)
    _RL[ip] = arr
    # 防内存无限增长：仅在字典过大时清理过期来源键
    if len(_RL) > 10000:
        for k in [k for k, v in list(_RL.items()) if not v or now - v[-1] > window]:
            _RL.pop(k, None)


ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _require_admin(request):
    # P0-3：仅允许请求头传令牌，禁止 URL 查询参数（避免进入日志/历史）
    tok = request.headers.get("X-Admin-Token")
    if not ADMIN_TOKEN or tok != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden: admin token required")


@app.middleware("http")
async def _guard_and_headers(request, call_next):
    _t0 = _time.time()
    # P0-4：请求体上限（在业务解析前拦截过大 body）
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_BODY:
                return JSONResponse({"detail": f"request body too large (>{MAX_BODY} bytes)"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
    resp = await call_next(request)
    try:
        dt = (_time.time() - _t0) * 1000.0
        _METRICS["total"] += 1
        _METRICS["latency_ms_sum"] += dt
        _METRICS["latency_max_ms"] = max(_METRICS["latency_max_ms"], dt)
        p = request.url.path
        _METRICS["by_path"][p] = _METRICS["by_path"].get(p, 0) + 1
        if p.startswith("/api/"):
            _METRICS["lat"].append(dt)
            if len(_METRICS["lat"]) > 500:
                del _METRICS["lat"][:250]
        if resp.status_code >= 500:
            _METRICS["errors"] += 1
    except Exception:  # noqa: BLE001
        pass
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return resp


def _refresh(do_fetch=True):
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "busy"}
    t0 = _time.time()
    try:
        import pipeline
        pipeline.run(do_fetch=do_fetch, do_ndvi=do_fetch, do_figs=False, do_reports=False)
        _advice_cache.clear()
        _save_snapshot(fetched_at=season.now().strftime("%Y-%m-%d %H:%M:%S"), note="scheduled/manual refresh")
        store.set_refresh_state("ok", round(_time.time() - t0, 1))
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        store.set_refresh_state("error", round(_time.time() - t0, 1), str(e))
        raise
    finally:
        _refresh_lock.release()


def _save_snapshot(fetched_at=None, note=""):
    """把当前预报按"版本"入库（含参数/构建/hash/真实抓取时间），用于数据血缘与新鲜度。"""
    try:
        import hashlib
        d = _load()
        days = [{"date": x["date"], "tmin": x.get("tmin"), "tmax": x.get("tmax"), "precip": x.get("precip"),
                 "p_frost": x.get("p_frost"), "p_heat": x.get("p_heat"),
                 "risk_R": x.get("risk_R"), "risk_level": x.get("risk_level")}
                for x in d["days"] if x["source"] == "forecast"]
        raw = json.dumps(days, ensure_ascii=False, sort_keys=True)
        meta = {"ts": season.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "Open-Meteo (ERA5 + forecast)", "model": "teawindow-pipeline",
                "gen_time": d.get("meta", {}).get("updated"),
                "fetched_at": fetched_at or (d.get("meta", {}) or {}).get("fetched_at") or d.get("meta", {}).get("updated"),
                "lat": d.get("meta", {}).get("lat"), "lon": d.get("meta", {}).get("lon"),
                "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()[:16],
                "build": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:12],
                "note": note}
        store.save_snapshot(meta, days)
    except Exception as e:  # noqa: BLE001
        print("[serve] snapshot skip:", e)


@app.get("/api/health")
def health():
    retr = None
    try:
        from qa import retriever
        retr = retriever.backend()
    except Exception:  # noqa: BLE001
        retr = None
    fr = _freshness() if os.path.exists(DATA_JSON) else {}
    return {"status": "ok", "data_ready": os.path.exists(DATA_JSON),
            "has_llm_key": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "retrieval": retr,
            "fetched_at": fr.get("fetched_at"), "age_minutes": fr.get("age_minutes"),
            "stale": fr.get("stale"), "build": fr.get("build"),
            "refresh": fr.get("refresh")}


@app.get("/api/overview")
def overview():
    return JSONResponse(_load())


@app.get("/api/summary", response_model=SummaryResp)
def summary():
    d = _load()
    days = d["days"]
    forecast = [x for x in days if x["source"] == "forecast"]
    n7 = forecast[:7]
    maxrisk = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else None
    cur = _cur_day(days)
    season_name = (d.get("meta", {}) or {}).get("season") or _season_of()
    # P0-1：非春采期不对外提供采摘窗口（统一季节策略）
    pick_window = d.get("pick_window", []) if season_name == "spring" else []
    return {
        "updated": d["meta"]["updated"],
        "fetched_at": (d.get("meta", {}) or {}).get("fetched_at", d["meta"].get("updated")),
        "age_minutes": _freshness(d)["age_minutes"],
        "stale": _freshness(d)["stale"],
        "season": season_name,
        "data_age_days": (season.today() - datetime.date.fromisoformat(str(cur["date"])[:10])).days if cur else None,
        "current": {"date": cur["date"], "risk_level": cur["risk_level"],
                    "risk_R": cur["risk_R"], "suitability": cur["suitability"]} if cur else None,
        "next7_max": {"date": maxrisk["date"], "risk_level": maxrisk["risk_level"],
                      "risk_R": maxrisk["risk_R"]} if maxrisk else None,
        "pick_window": pick_window,
        "pick_window_note": d.get("pick_window_note"),
        "metrics": d.get("metrics", {}).get("ml", {}),
    }


@app.get("/api/days")
def days(scope: str = "recent"):
    if scope not in ("recent", "forecast", "history"):
        raise HTTPException(422, "scope must be 'recent' | 'forecast' | 'history'")
    d = _load()
    if scope == "forecast":
        today = season.iso_today()
        return {"scope": scope, "days": [x for x in d["days"] if x["source"] == "forecast" and x["date"] >= today]}
    if scope == "history":
        return {"scope": scope, "days": [x for x in d["days"] if x["source"] == "history"]}
    return {"scope": scope, "days": d["days"]}


@app.get("/api/advice")
def advice(date: str):
    if date in _advice_cache:
        return _advice_cache[date]
    d = _load()
    row = next((x for x in d["days"] if x["date"] == date), None)
    if row is None:
        raise HTTPException(404, f"未找到日期 {date}")
    if not _llm_spend():
        return {"source": "budget_fallback", "date": date,
                "text": row.get("advice") or "LLM 每日预算已用尽，返回自研规则建议。"}
    ctx = llm_advice.ctx_from_row(_to_serieslike(row))
    out = llm_advice.generate(ctx)
    out["date"] = date
    _advice_cache[date] = out
    return out


def _to_serieslike(row):
    """把单日 dict 适配成 ctx_from_row 可用的映射，并补算派生字段。"""
    r = dict(row)
    r.setdefault("temperature_2m_max", row.get("tmax"))
    r.setdefault("temperature_2m_min", row.get("tmin"))
    r.setdefault("precipitation_sum", row.get("precip"))
    r.setdefault("water_deficit_10d", row.get("deficit"))
    for k in ("frost", "cold_shock", "heat", "heat_severe", "dry_run", "wet_run", "risk_R", "suitability"):
        r[k] = row.get(k, 0) or 0
    return r


# ---- 对话式问答（N3）----
def _context():
    d = _load()
    days = d["days"]
    hist = [x for x in days if x["source"] == "history"]
    fc = [x for x in days if x["source"] == "forecast"]
    cur = _cur_day(days)
    n7 = fc[:7]
    mx = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else None
    dec = d.get("decision") or {}
    sch = (d.get("schedule") or {}).get("schedule", [])
    season = (d.get("meta", {}) or {}).get("season") or _season_of()
    season_off = (season == "off")
    return {
        "season": season,
        "current": ({"date": cur["date"], "risk_level": cur.get("risk_level"),
                     "risk_R": cur.get("risk_R"), "suitability": cur.get("suitability")} if cur else None),
        "next7_max": ({"date": mx["date"], "risk_level": mx.get("risk_level"),
                       "risk_R": mx.get("risk_R")} if mx else None),
        "pick_window": [] if season_off else d.get("pick_window", []),
        "best_pick_day": None if season_off else dec.get("best_pick_day"),
        "schedule": ([] if season_off else
                     [{"date": s["date"], "plots": [p["name"] for p in s["plots"]]} for s in sch]),
        "metrics_auc": (d.get("metrics", {}).get("ml", {}) or {}).get("auc"),
        "value": d.get("value"),
    }


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class AskReq(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    engine: str = "own"   # own=自研引擎(默认)；llm=DeepSeek 可选增强
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    state: dict | None = None   # 结构化会话槽位（active_date/format/negated…）

    @field_validator("question", mode="before")
    @classmethod
    def _strip_question(cls, v):
        if isinstance(v, str):
            v = v.strip()
        if not v:
            raise ValueError("question must be non-empty after trimming")
        return v


class ErrorResp(BaseModel):
    detail: str


class OutcomeReq(BaseModel):
    date: str
    plot: str = ""
    kind: str = ""            # 采摘 / 霜冻受灾 / 高温灼伤 / 连阴雨 / 产量 / 品质 / 其他
    area_mu: float | None = None
    damage_level: str = ""    # 无 / 轻 / 中 / 重
    yield_kg: float | None = None
    quality: str = ""
    note: str = ""


# 运行指标（进程内，用于监控/告警）
_METRICS = {"total": 0, "errors": 0, "by_path": {}, "latency_ms_sum": 0.0, "latency_max_ms": 0.0, "lat": []}


def _ask(q, engine, history=None, state=None):
    from qa import engine as qa_engine
    try:
        fut = _ASK_EXEC.submit(qa_engine.answer, q, _context(), history or [], state or {})
        base = fut.result(timeout=float(os.environ.get("ASK_TIMEOUT", "20")))
    except _cf.TimeoutError:
        base = {"engine": "teawindow-own", "mode": "rules", "intent": "timeout", "confidence": 0.0,
                "backend": None, "retrieval": None,
                "text": "抱歉，本次处理超时。请简化问题（如：今天有风险吗 / 要不要防冻 / 先采哪块地）后重试。"}
    except Exception:  # noqa: BLE001
        base = {"engine": "teawindow-own", "mode": "rules", "intent": "error", "confidence": 0.0,
                "backend": None, "retrieval": None, "text": "抱歉，处理出错，请稍后重试或换个说法。"}
    if engine == "llm":
        if not _llm_spend():
            # P0-4：每日预算用尽 → 直接回退自研规则，不调用外部模型
            out = dict(base)
            out["source"] = "budget_fallback"
            out["note"] = "LLM 每日预算已用尽，本次返回自研规则答案。"
            return out
        # P0-1：LLM 只润色，数值/结论/极性/季节以规则为准，校验失败回退规则
        rep = llm_advice.rephrase_keep_numbers(q, base["text"])
        out = dict(base)
        out["engine"] = "teawindow-own+llm"
        out["source"] = rep["source"]
        out["base_text"] = base["text"]
        out["text"] = rep["text"]
        return out
    return base


@app.post("/api/ask", response_model=AskResp,
          responses={422: {"model": ErrorResp}, 429: {"model": ErrorResp}})
def ask(request: Request, req: AskReq):
    if req.engine not in ("own", "llm"):
        raise HTTPException(422, "engine must be 'own' or 'llm'")
    ip = request.client.host if request.client else "global"
    if req.engine == "llm":
        _rate_limit("llm:" + ip, limit=int(os.environ.get("LLM_RPM", "8")))
    _rate_limit(ip, limit=int(os.environ.get("ASK_RPM", "40")))
    hist = [{"role": m.role, "content": m.content[:500]} for m in req.history[-8:]]
    return _ask(req.question.strip(), req.engine, hist, req.state)


@app.get("/api/ask", response_model=AskResp)
def ask_get(request: Request, q: str, engine: str = "own"):
    if engine not in ("own", "llm"):
        raise HTTPException(422, "engine must be 'own' or 'llm'")
    q = (q or "").strip()
    if not q:
        raise HTTPException(422, "q must be a non-empty question (<=500 chars)")
    if len(q) > 500:
        raise HTTPException(422, "q too long (<=500 chars)")
    ip = request.client.host if request.client else "global"
    if engine == "llm":
        _rate_limit("llm:" + ip, limit=int(os.environ.get("LLM_RPM", "8")))
    _rate_limit(ip, limit=int(os.environ.get("ASK_RPM", "40")))
    return _ask(q, engine, [])


# ---- 众包物候上报（N4）----
KINDS = {"开采", "倒春寒/霜冻", "高温灼伤", "连阴雨", "其他"}


class ReportReq(BaseModel):
    date: str
    plot: str = ""
    kind: str = ""   # 开采 / 受冻 / 灼伤 / 其他
    note: str = ""


@app.post("/api/report")
def report(request: Request, req: ReportReq):
    import datetime as _dt
    ip = request.client.host if request.client else "global"
    _rate_limit(ip, limit=int(os.environ.get("REPORT_RPM", "10")))
    if req.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    try:
        _dt.date.fromisoformat(req.date)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "date must be YYYY-MM-DD")
    rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"),
           "date": req.date[:10], "plot": (req.plot or "")[:40],
           "kind": req.kind, "note": (req.note or "")[:200]}
    n = store.add_report(rec)
    return {"status": "ok", "count": n}


@app.get("/api/reports")
def reports(request: Request):
    _require_admin(request)   # P1-2：上报内容默认不公开
    items = store.list_reports(50)
    return {"count": len(items), "items": items}


# ---- 传感器数据接入（第三方硬件上报）----
SENSOR_TOKEN = os.environ.get("SENSOR_TOKEN", "")
_SENSOR_FIELDS = ("temp", "rh", "soil_moisture", "soil_temp", "precip", "wind", "light", "vpd")
_SENSOR_RANGE = {"temp": (-30, 60), "rh": (0, 100), "soil_moisture": (0, 1),
                 "soil_temp": (-30, 60), "precip": (0, 500), "wind": (0, 80),
                 "light": (0, 200000), "vpd": (0, 10)}


class SensorReq(BaseModel):
    station_id: str
    ts: str                      # ISO8601，例如 2026-10-13T08:00:00+08:00
    temp: float | None = None
    rh: float | None = None
    soil_moisture: float | None = None
    soil_temp: float | None = None
    precip: float | None = None
    wind: float | None = None
    light: float | None = None
    vpd: float | None = None
    note: str = ""


class SensorBatch(BaseModel):
    readings: list["SensorReq"] = Field(default_factory=list, max_length=500)


def _require_sensor(request):
    # P0-3：仅允许请求头传令牌（X-Sensor-Token / Authorization: Bearer）；设备级令牌按哈希校验
    tok = (request.headers.get("X-Sensor-Token")
           or request.headers.get("Authorization", "").replace("Bearer ", ""))
    valid = {t for t in (SENSOR_TOKEN, ADMIN_TOKEN) if t}
    if (tok and tok in valid) or (tok and store.verify_device(tok)):
        return
    raise HTTPException(403, "forbidden: sensor token required")


def _valid_sensor(req):
    import re as _re
    sid = (req.station_id or "").strip()
    if not _re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", sid):
        raise HTTPException(422, "station_id must match [A-Za-z0-9_-]{1,40}")
    try:
        dt = datetime.datetime.fromisoformat(req.ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "ts must be ISO8601")
    # 时间漂移校验：不接受超前 2 天以上的设备时间（防重放/时钟错误）
    now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
    if dt > now + datetime.timedelta(days=2):
        raise HTTPException(422, "ts is too far in the future (device clock drift?)")
    rec = {"ts": req.ts[:32], "station_id": sid, "received": datetime.datetime.now().isoformat(timespec="seconds")}
    n = 0
    for f in _SENSOR_FIELDS:
        v = getattr(req, f)
        if v is None:
            continue
        lo, hi = _SENSOR_RANGE[f]
        if not (lo <= v <= hi):
            raise HTTPException(422, f"{f} out of range [{lo},{hi}]")
        rec[f] = round(float(v), 3)
        n += 1
    if n == 0:
        raise HTTPException(422, "at least one measurement required")
    rec["note"] = (req.note or "")[:200]
    return rec


@app.post("/api/sensor")
def sensor(request: Request, req: SensorReq):
    _require_sensor(request)
    ip = request.client.host if request.client else "global"
    _rate_limit(ip, limit=int(os.environ.get("SENSOR_RPM", "120")))
    accepted, n = store.add_sensor([_valid_sensor(req)])
    return {"status": "ok", "accepted": accepted, "count": n, "dedup": accepted == 0}


@app.post("/api/sensor/batch")
def sensor_batch(request: Request, req: SensorBatch):
    _require_sensor(request)
    ip = request.client.host if request.client else "global"
    _rate_limit(ip, limit=int(os.environ.get("SENSOR_RPM", "120")))
    if not req.readings:
        raise HTTPException(422, "readings must be a non-empty list (<=500)")
    recs = [_valid_sensor(r) for r in req.readings]
    accepted, n = store.add_sensor(recs)
    return {"status": "ok", "accepted": accepted, "count": n}


@app.get("/api/realtime")
def realtime():
    """公开只读：各站最新观测 + 新鲜度（observed_at/received_at/age_seconds/status）。"""
    latest = store.sensor_latest()
    keep = ("ts", "temp", "rh", "soil_moisture", "soil_temp", "precip", "wind", "light", "vpd")
    stations = {}
    latest_obs = None
    for sid, r in latest.items():
        age = None
        try:
            rec = datetime.datetime.fromisoformat(str(r.get("received")))
            age = (datetime.datetime.now() - rec).total_seconds()
        except Exception:  # noqa: BLE001
            age = None
        if age is None:
            status = "unknown"
        elif age > 86400:
            status = "offline"
        elif age > 3600:
            status = "stale"
        else:
            status = "ok"
        pub = {k: r.get(k) for k in keep if r.get(k) is not None}
        pub.update({"observed_at": r.get("ts"), "received_at": r.get("received"),
                    "age_seconds": None if age is None else int(age), "status": status})
        stations[sid] = pub
        if latest_obs is None or str(r.get("ts")) > str(latest_obs):
            latest_obs = r.get("ts")
    n = store.sensor_count()
    return {"server_time": season.now().isoformat(timespec="seconds"),
            "updated": season.now().isoformat(timespec="seconds"),
            "n": n, "count": n, "latest_observation_at": latest_obs,
            "status": "ok" if stations else "no_sensors",
            "message": None if stations else "尚未接入现场传感器（0 个站点上报）",
            "stations": stations}


@app.get("/api/sensor/latest")
def sensor_latest(request: Request, station_id: str = "", limit: int = 20):
    _require_sensor(request)
    items = store.sensor_items(station_id, limit)
    latest = {}
    for r in items:
        sid = r.get("station_id")
        if sid and (sid not in latest or str(r.get("ts")) > str(latest[sid].get("ts"))):
            latest[sid] = r
    return {"count": store.sensor_count(), "stations": sorted(latest.keys()),
            "latest": latest, "items": items}


# ---- 物候/灾情上报（众包）已在上方 /api/report ----

@app.post("/api/refresh")
def refresh(request: Request, background: BackgroundTasks, fetch: bool = True):
    _require_admin(request)
    background.add_task(_refresh, fetch)
    return {"status": "scheduled", "fetch": fetch}


# ---- 定时任务：每日 06:00 + 每 3 小时刷新（若有 apscheduler）----
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _sched = BackgroundScheduler(timezone="Asia/Shanghai")
    _sched.add_job(lambda: _refresh(True), "cron", hour=6, minute=0, id="daily_refresh")
    _sched.add_job(lambda: _refresh(True), "cron", hour="0,3,9,12,15,18,21", minute=20, id="refresh_3h",
                   replace_existing=True)
    _sched.start()
    print("[serve] 已启用定时刷新（每日 06:00 + 每 3 小时）")
except Exception as e:  # noqa: BLE001
    print("[serve] 未启用定时任务:", e)


# ---- 数据版本 / 预报快照 / 数据血缘（供第三方与审计） ----
VERIFY_JSON = os.path.join(ROOT, "report", "forecast_verify.json")


@app.get("/api/data/versions")
def data_versions(limit: int = 10):
    return {"count": store.version_count(), "versions": store.list_versions(limit)}


@app.post("/api/data/snapshot")
def data_snapshot(request: Request):
    _require_admin(request)
    _save_snapshot()
    return {"status": "ok", "count": store.version_count()}


@app.get("/api/forecast/verify")
def forecast_verify():
    """提前期真实误差（权威在线归档 Previous Runs vs ERA5）。"""
    if not os.path.exists(VERIFY_JSON):
        return {"status": "pending", "note": "调用 POST /api/forecast/verify/refresh 生成"}
    return JSONResponse(json.load(open(VERIFY_JSON, encoding="utf-8")))


@app.post("/api/forecast/verify/refresh")
def forecast_verify_refresh(request: Request, background: BackgroundTasks, days: int = 60):
    _require_admin(request)

    def _run():
        try:
            import forecast_verify as fv
            sys.argv = ["forecast_verify", "--days", str(days)]
            fv.main()
        except Exception as e:  # noqa: BLE001
            print("[verify] refresh failed:", e)

    background.add_task(_run)
    return {"status": "scheduled", "days": days}


# ---- 设备级凭证 + 审计（共享静态令牌的进阶方案） ----
@app.post("/api/device/register")
def device_register(request: Request, device_id: str):
    _require_admin(request)
    import secrets
    tok = secrets.token_urlsafe(24)
    store.register_device(device_id, tok)
    return {"device_id": device_id, "token": tok, "note": "请安全保存；服务端仅存哈希，可 revoke"}


@app.post("/api/device/revoke")
def device_revoke(request: Request, device_id: str):
    _require_admin(request)
    store.revoke_device(device_id)
    return {"status": "revoked", "device_id": device_id}


@app.get("/api/devices")
def devices(request: Request):
    _require_admin(request)
    return {"active": store.device_count(), "audit": store.list_audit(50)}


# ---- 田间结果（前瞻性盲测真值）+ 盲测评估 ----
@app.post("/api/outcome")
def outcome(request: Request, req: OutcomeReq):
    _require_sensor(request)   # 设备令牌或传感器令牌
    import datetime as _dt
    try:
        _dt.date.fromisoformat(req.date)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "date must be YYYY-MM-DD")
    if req.kind not in store.OUTCOME_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(store.OUTCOME_KINDS)}")
    n = store.add_outcome({"ts": _dt.datetime.now().isoformat(timespec="seconds"), "date": req.date[:10],
                           "plot": (req.plot or "")[:40], "kind": req.kind, "area_mu": req.area_mu,
                           "damage_level": (req.damage_level or "")[:16], "yield_kg": req.yield_kg,
                           "quality": (req.quality or "")[:40], "note": (req.note or "")[:200]})
    return {"status": "ok", "count": n}


@app.get("/api/outcomes")
def outcomes(request: Request, limit: int = 100):
    _require_admin(request)
    return {"count": store.outcome_count(), "items": store.list_outcomes(limit)}


@app.get("/api/pilot/evaluate")
def pilot_evaluate(request: Request):
    """前瞻性盲测评估：快照 × 田间结果按日期配对，输出事件级混淆矩阵/提前量（可复算）。"""
    _require_admin(request)
    return store.pilot_evaluate()


# ---- 运行指标 / 告警 / 实时更新 ----
@app.get("/api/metrics")
def metrics(request: Request):
    _require_admin(request)
    lat = sorted(_METRICS["lat"])
    def pct(q):
        if not lat:
            return None
        i = min(len(lat) - 1, int(round(q * (len(lat) - 1))))
        return round(lat[i], 1)
    avg = (_METRICS["latency_ms_sum"] / _METRICS["total"]) if _METRICS["total"] else 0
    fr = _freshness() if os.path.exists(DATA_JSON) else {}
    return {"requests": _METRICS["total"], "errors_5xx": _METRICS["errors"],
            "latency_avg_ms": round(avg, 1), "latency_max_ms": round(_METRICS["latency_max_ms"], 1),
            "latency_p50_ms": pct(0.50), "latency_p95_ms": pct(0.95), "latency_p99_ms": pct(0.99),
            "by_path": _METRICS["by_path"],
            "data_age_minutes": fr.get("age_minutes"), "data_stale": fr.get("stale"),
            "refresh": fr.get("refresh"), "build": fr.get("build"),
            "llm_usage": _llm_usage, "llm_daily_budget": LLM_DAILY_BUDGET,
            "sensor_count": store.sensor_count(), "device_active": store.device_count(),
            "versions": store.version_count(), "outcomes": store.outcome_count()}


@app.get("/api/updates")
def updates(since: str = ""):
    """轻量实时：服务器时间 + 各来源计数；`since` 为 ISO 时间则只返回其后新增观测（真增量）。"""
    latest = store.sensor_latest()
    keep = ("ts", "temp", "rh", "soil_moisture", "soil_temp", "precip", "wind", "light", "vpd")
    sin = (since or "").strip()
    if sin:
        items = [r for r in store.sensor_items("", 500) if str(r.get("received", "")) > sin]
        stations = {}
        for r in items:
            stations[r.get("station_id")] = {k: r.get(k) for k in keep if r.get(k) is not None}
        return {"server_time": season.now().isoformat(timespec="seconds"), "since": sin,
                "incremental": True, "new_sensor": len(items), "stations": stations}
    pub = {sid: {k: r.get(k) for k in keep if r.get(k) is not None} for sid, r in latest.items()}
    return {"server_time": season.now().isoformat(timespec="seconds"),
            "sensor_count": store.sensor_count(), "outcome_count": store.outcome_count(),
            "version_count": store.version_count(), "stations": pub,
            "latest_version": (store.list_versions(1) or [None])[0]}


@app.get("/api/phenology/validation")
def phenology_validation():
    p = os.path.join(ROOT, "report", "phenology_validation.md")
    if not os.path.exists(p):
        return {"status": "pending"}
    return {"status": "ready", "report": open(p, encoding="utf-8").read()}


# 静态站点挂到最后，"/" 作为兜底（API 路由优先）
if os.path.isdir(WEB):
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8000, reload=False)
