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

    def _boot_tasks():
        _sync_data_from_db()   # 先把 DB 中更新的构建产物同步回本地（跨实例轮换）
        _ensure_raw()          # 确保原始 archive/forecast 缓存存在（跨实例轮换、archive 限流回退）
        # 预加载模型（意图 ONNX + 检索索引），避免首个请求触发冷加载超时
        try:
            from qa import intent_onnx, retriever
            intent_onnx.available()
            if retriever.available():
                retriever._index_vectors()
            print("[serve] 模型预热完成")
        except Exception as e:  # noqa: BLE001
            print("[serve] 模型预热跳过:", e)
        # 记录初始数据版本与刷新状态（数据血缘）
        try:
            if store.version_count() == 0 and os.path.exists(DATA_JSON):
                _save_snapshot(note="startup-existing（沿用已有加工数据，非新抓取）")
                print("[serve] 初始数据版本已记录（沿用已有数据）")
            if store.get_refresh_state().get("status") == "unknown":
                store.set_refresh_state("startup", 0.0)
        except Exception as e:  # noqa: BLE001
            print("[serve] 初始快照状态跳过:", e)
        # 预热上游漂移比对（否则部署后 /api/ready 会因 compare_not_run 短暂非就绪）
        try:
            _compare_upstream(force=True)
            print("[serve] 上游漂移比对预热完成")
        except Exception as e:  # noqa: BLE001
            print("[serve] 比对预热跳过:", e)

    threading.Thread(target=_boot_tasks, daemon=True).start()   # 后台预热，避免阻塞启动/健康检查
    yield


app = FastAPI(title="TeaWindow API", version="1.0",
              description="梅家坞龙井复合气候风险与采摘窗口决策助手",
              lifespan=_lifespan)

# 请求体上限（P0-4：超大 body 在网络/解析前拒绝）
MAX_BODY = int(os.environ.get("MAX_BODY_BYTES", "65536"))
# LLM 每日预算（P0-4：昂贵调用独立配额）
LLM_DAILY_BUDGET = int(os.environ.get("LLM_DAILY_BUDGET", "300"))
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")
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


STALE_MINUTES = int(os.environ.get("STALE_MINUTES", "90"))
_COMPARE = {"ts": 0.0, "result": None}


def _upstream_daily():
    """取上游最新逐日预报（tmax/tmin/precip），用于漂移比对。
    优先与主源一致；Open-Meteo 失败（如免费档 429）时回退 MET Norway。返回 (map, source)。"""
    import requests
    d = _load()
    lat = d.get("meta", {}).get("lat", 30.2139)
    lon = d.get("meta", {}).get("lon", 120.0961)
    import fetch_weather
    ua = getattr(fetch_weather, "UA", "TeaWindow/1.0 (contact: 2302372846@qq.com)")

    def from_om():
        params = {"latitude": lat, "longitude": lon,
                  "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                  "forecast_days": 16, "timezone": "Asia/Shanghai"}
        url = "https://api.open-meteo.com/v1/forecast"
        _omk = os.environ.get("OPEN_METEO_API_KEY", "")
        if _omk:
            url = "https://customer-api.open-meteo.com/v1/forecast"
            params["apikey"] = _omk
        r = None
        for i in range(3):
            r = requests.get(url, params=params, timeout=30, headers={"User-Agent": ua})
            if r.status_code != 429:
                break
            _time.sleep(int(r.headers.get("Retry-After", 0)) or (6 * (i + 1)))
        r.raise_for_status()
        up = r.json()["daily"]
        return {day: {"tmax": up["temperature_2m_max"][i], "tmin": up["temperature_2m_min"][i],
                      "precip": up["precipitation_sum"][i]} for i, day in enumerate(up["time"])}

    def from_metno():
        up = fetch_weather.fetch_forecast_metno(16)["daily"]
        return {day: {"tmax": up["temperature_2m_max"][i], "tmin": up["temperature_2m_min"][i],
                      "precip": up["precipitation_sum"][i]} for i, day in enumerate(up["time"])}

    primary = os.environ.get("FORECAST_SOURCE", "auto")
    if primary == "metno":
        try:
            return from_metno(), "met.no"
        except Exception:  # noqa: BLE001
            return from_om(), "open-meteo"
    try:
        return from_om(), "open-meteo"
    except Exception:  # noqa: BLE001
        return from_metno(), "met.no"


def _compare_upstream(force=False):
    """把本地快照与上游最新逐日预报比对（change-warning）。结果缓存 30 分钟。"""
    now = _time.time()
    if not force and _COMPARE["result"] is not None and (now - _COMPARE["ts"]) < 1800:
        return _COMPARE["result"]
    try:
        d = _load()
        fc = {x["date"]: x for x in d["days"] if x["source"] == "forecast"}
        upm, up_src = _upstream_daily()
        dmax = dprecip = 0.0
        n = 0
        for day in set(fc) & set(upm):
            a, b = fc[day], upm[day]
            if a.get("tmax") is not None and b.get("tmax") is not None:
                dmax = max(dmax, abs(a["tmax"] - b["tmax"]))
            if a.get("precip") is not None and b.get("precip") is not None:
                dprecip = max(dprecip, abs((a["precip"] or 0) - (b["precip"] or 0)))
            n += 1
        res = {"ts": season.now().isoformat(timespec="seconds"), "n_days": n, "upstream": up_src,
               "max_tmax_delta": round(dmax, 1), "max_precip_delta": round(dprecip, 1),
               "changed": bool(dmax >= 3 or dprecip >= 5),
               "note": "本地快照 vs 上游最新（同坐标）；差异大即决策级漂移，应视为可能过期。"}
    except Exception as e:  # noqa: BLE001
        res = {"ts": season.now().isoformat(timespec="seconds"), "error": repr(e)[:160]}
        _COMPARE.update(ts=now - 1500, result=res)   # 失败时缩短缓存（约 5 分钟后再试）
        return res
    _COMPARE.update(ts=now, result=res)
    return res


def _lineage_ok():
    try:
        v = store.list_versions(1)
        if not v:
            return False
        return bool(v[0].get("upstream_url")) and bool(v[0].get("raw_sha256_full"))
    except Exception:  # noqa: BLE001
        return False


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
            if (_time.time() - _BOOT_TS) < COLD_WINDOW_S:
                _METRICS["cold"].append(dt)
            else:
                _METRICS["hot"].append(dt)
            for k in ("lat", "cold", "hot"):
                if len(_METRICS[k]) > 500:
                    del _METRICS[k][:250]
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


def _refresh(do_fetch=True, light=True):
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "busy"}
    t0 = _time.time()
    _saved_argv = sys.argv
    sys.argv = ["pipeline"]   # 避免 uvicorn 命令行参数污染下游模块（如 fetch_weather 读 argv 当日期）
    if light and do_fetch:
        os.environ["TW_FETCH_FORECAST_ONLY"] = "1"   # 轻量：仅抓预报，避免上游限流
    try:
        import pipeline
        pipeline.run(do_fetch=do_fetch, do_ndvi=(do_fetch and not light), do_figs=False, do_reports=False)
        _advice_cache.clear()
        _save_snapshot(fetched_at=season.now().strftime("%Y-%m-%d %H:%M:%S"),
                       note=("light refresh" if light else "full refresh"))
        try:   # 把构建产物存入 DB，保证跨实例轮换不丢（免费层容器磁盘会重置）
            with open(DATA_JSON, encoding="utf-8") as f:
                blob = f.read()
            store.set_data_json(json.loads(blob).get("meta", {}).get("updated") or season.now().strftime("%Y-%m-%d %H:%M:%S"), blob)
        except Exception as e:  # noqa: BLE001
            print("[serve] data.json 入库跳过:", e)
        _persist_raw()   # 原始缓存入库，跨实例轮换后可恢复（避免 archive 429 导致刷新失败）
        try:   # 刷新后立即重跑漂移比对，保证 decision_ready 就绪
            _compare_upstream(force=True)
        except Exception as e:  # noqa: BLE001
            print("[serve] 刷新后比对跳过:", e)
        store.set_refresh_state("ok", round(_time.time() - t0, 1),
                                next_planned=(season.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"))
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        store.set_refresh_state("error", round(_time.time() - t0, 1), str(e),
                                next_planned=(season.now() + datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"))
        raise
    finally:
        sys.argv = _saved_argv
        os.environ.pop("TW_FETCH_FORECAST_ONLY", None)
        _refresh_lock.release()


def _sync_data_from_db():
    """启动时若 DB 中构建产物的时间更新，则同步回 web/data.json / data.js（跨实例轮换持久）。"""
    try:
        dj = store.get_data_json()
        if not dj or not dj.get("blob"):
            return
        cur_ts = None
        if os.path.exists(DATA_JSON):
            try:
                cur_ts = (_load().get("meta", {}) or {}).get("updated")
            except Exception:  # noqa: BLE001
                cur_ts = None
        if not cur_ts or str(dj["ts"]) > str(cur_ts):
            with open(DATA_JSON, "w", encoding="utf-8") as f:
                f.write(dj["blob"])
            with open(os.path.join(WEB, "data.js"), "w", encoding="utf-8") as f:
                f.write("window.TW_DATA = " + dj["blob"] + ";\n")
            print("[serve] 已从数据库同步 data.json:", dj["ts"])
    except Exception as e:  # noqa: BLE001
        print("[serve] data.json 同步跳过:", e)


def _ensure_raw():
    """确保 data/raw 下有 archive/forecast 缓存（跨实例轮换）：优先 DB，其次由现有构建产物重建。"""
    raw = os.path.join(ROOT, "data", "raw")
    os.makedirs(raw, exist_ok=True)
    ap = os.path.join(raw, "weather_archive.json")
    fp = os.path.join(raw, "weather_forecast.json")
    amap = {"temperature_2m_max": "tmax", "temperature_2m_min": "tmin", "temperature_2m_mean": "tmean",
            "precipitation_sum": "precip", "relative_humidity_2m_mean": "rh", "et0_fao_evapotranspiration": "et0",
            "sunshine_duration": "sun_s", "wind_speed_10m_max": "wind", "soil_moisture_0_to_7cm_mean": "soil",
            "shortwave_radiation_sum": None}
    try:
        if not os.path.exists(ap):
            blob = store.get_raw("weather_archive.json")
            base = os.path.join(ROOT, "data", "archive_baseline.json")
            baseblob = None
            if os.path.exists(base):
                try:
                    baseblob = open(base, encoding="utf-8").read()
                except Exception:  # noqa: BLE001
                    baseblob = None

            def _n(b):
                try:
                    return len(json.loads(b).get("daily", {}).get("time", []))
                except Exception:  # noqa: BLE001
                    return 0
            # 取"更长"的归档（完整基线优先），避免被短归档污染
            pick = blob if _n(blob or "") >= _n(baseblob or "") else baseblob
            if pick:
                open(ap, "w", encoding="utf-8").write(pick)
                try:
                    store.set_raw("weather_archive.json", pick)
                except Exception:  # noqa: BLE001
                    pass
                print("[serve] 恢复 archive 缓存（天数=%d）" % _n(pick))
            else:
                hist = [x for x in _load().get("days", []) if x.get("source") == "history"]
                if hist:
                    arc = {"daily": {"time": [x["date"] for x in hist]}, "_fallback": "from-build"}
                    for k, s in amap.items():
                        arc["daily"][k] = [x.get(s) if s else None for x in hist]
                    blob = json.dumps(arc, ensure_ascii=False)
                    open(ap, "w", encoding="utf-8").write(blob)
                    store.set_raw("weather_archive.json", blob)
                    print("[serve] 由构建历史重建 archive 缓存")
        if not os.path.exists(fp):
            blob = store.get_raw("weather_forecast.json")
            if blob:
                open(fp, "w", encoding="utf-8").write(blob)
                print("[serve] 从数据库恢复 forecast 缓存")
            else:
                fcs = [x for x in _load().get("days", []) if x.get("source") == "forecast"]
                if fcs:
                    out = {"latitude": 30.2139, "longitude": 120.0961, "timezone": "Asia/Shanghai",
                           "_source": "from-build",
                           "daily": {"time": [x["date"] for x in fcs],
                                     "temperature_2m_max": [x.get("tmax") for x in fcs],
                                     "temperature_2m_min": [x.get("tmin") for x in fcs],
                                     "temperature_2m_mean": [x.get("tmean") for x in fcs],
                                     "precipitation_sum": [x.get("precip") for x in fcs],
                                     "relative_humidity_2m_mean": [x.get("rh") for x in fcs]}}
                    blob = json.dumps(out, ensure_ascii=False)
                    open(fp, "w", encoding="utf-8").write(blob)
                    store.set_raw("weather_forecast.json", blob)
                    print("[serve] 由构建产物重建 forecast 缓存")
    except Exception as e:  # noqa: BLE001
        print("[serve] raw 缓存确保跳过:", e)


def _persist_raw():
    for fn in ("weather_archive.json", "weather_forecast.json"):
        p = os.path.join(ROOT, "data", "raw", fn)
        try:
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    store.set_raw(fn, f.read())
        except Exception as e:  # noqa: BLE001
            print("[serve] raw 入库跳过:", fn, e)


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
        fm = {}
        try:
            fmp = os.path.join(ROOT, "data", "processed", "fetch_meta.json")
            if os.path.exists(fmp):
                fm = json.load(open(fmp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            fm = {}
        source = "Open-Meteo (ERA5 + forecast)"
        if fm.get("forecast_source") in ("met.no", "cached"):
            source = f"Open-Meteo(ERA5) + {fm.get('forecast_source')}"
        meta = {"ts": season.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": source, "model": "teawindow-pipeline",
                "gen_time": d.get("meta", {}).get("updated"),
                "fetched_at": fetched_at or fm.get("fetched_at") or (d.get("meta", {}) or {}).get("fetched_at") or d.get("meta", {}).get("updated"),
                "lat": d.get("meta", {}).get("lat"), "lon": d.get("meta", {}).get("lon"),
                "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()[:16],
                "raw_sha256_full": fm.get("forecast_raw_sha256"),
                "upstream_url": fm.get("forecast_url"),
                "params": json.dumps(fm.get("forecast_params"), ensure_ascii=False) if fm else None,
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
    age = None
    fetched = None
    try:
        if os.path.exists(DATA_JSON):
            meta = (_load().get("meta", {}) or {})
            fetched = meta.get("fetched_at") or meta.get("updated")
            fdt = datetime.datetime.fromisoformat(str(fetched))
            now = season.now()
            if fdt.tzinfo is None:
                now = now.replace(tzinfo=None)
            age = round((now - fdt).total_seconds() / 60.0, 1)
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok", "data_ready": os.path.exists(DATA_JSON),
            "has_llm_key": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "retrieval": retr, "fetched_at": fetched, "age_minutes": age,
            "stale": bool(age is not None and age > STALE_MINUTES),
            "build": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:12]}


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
    history: list[HistoryMessage] = Field(default_factory=list, max_length=24)
    state: dict | None = None   # 结构化会话槽位（active_date/format/negated/summary…）

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
_METRICS = {"total": 0, "errors": 0, "by_path": {}, "latency_ms_sum": 0.0, "latency_max_ms": 0.0,
            "lat": [], "cold": [], "hot": []}
_BOOT_TS = _time.time()
COLD_WINDOW_S = int(os.environ.get("COLD_WINDOW_S", "90"))   # 启动后 N 秒内视为冷启动


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


def _log_qa(request, req, out):
    """匿名记录一条问答（不含 IP/身份，按天加盐哈希）；用于教师纠偏与回训。"""
    try:
        if os.environ.get("QA_LOG", "1") != "1":
            return
        q = (req.question or "").strip()
        if len(q) < 2 or len(q) > 500:
            return
        import hashlib
        ip = request.client.host if request.client else "?"
        salt = datetime.date.today().isoformat()
        anon = hashlib.sha256((salt + "|" + ip).encode()).hexdigest()[:12]
        threading.Thread(target=store.qa_log_add,
                         args=(anon, q, out.get("intent"), out.get("text"), req.engine),
                         daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/ask", response_model=AskResp,
          responses={422: {"model": ErrorResp}, 429: {"model": ErrorResp}})
def ask(request: Request, req: AskReq):
    if req.engine not in ("own", "llm"):
        raise HTTPException(422, "engine must be 'own' or 'llm'")
    ip = request.client.host if request.client else "global"
    if req.engine == "llm":
        _rate_limit("llm:" + ip, limit=int(os.environ.get("LLM_RPM", "8")))
    _rate_limit(ip, limit=int(os.environ.get("ASK_RPM", "40")))
    hist = [{"role": m.role, "content": m.content[:500]} for m in req.history[-10:]]   # 记忆窗口≈10 条
    out = _ask(req.question.strip(), req.engine, hist, req.state)
    _log_qa(request, req, out)
    return out


@app.get("/api/qa/logs")
def qa_logs(request: Request, limit: int = 100):
    """管理员：查看待纠偏的匿名问答（不含 IP/身份）。"""
    _require_admin(request)
    return {"count": store.qa_log_count(), "pending": store.qa_log_pending(limit)}


class QAReviewReq(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    relevant: int | None = None
    teacher: str | None = None
    reviewed: int = 1


@app.post("/api/qa/review")
def qa_review(request: Request, req: QAReviewReq):
    """管理员：标记某条匿名问答（相关性/教师参考/是否已审阅）。"""
    _require_admin(request)
    store.qa_log_set(req.id, teacher=req.teacher, teacher_model="admin",
                     relevant=req.relevant, reviewed=req.reviewed)
    return {"ok": True, "id": req.id, "count": store.qa_log_count()}


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


def _verify_device(request, body: bytes):
    """设备签名校验（HMAC-SHA256 + 时间戳 + nonce 防重放）。
    签名规范：X-Signature = HMAC_SHA256(sha256(token),
        "{X-Timestamp}\\n{X-Nonce}\\n{METHOD}\\n{PATH}\\n{sha256(body)}")
    全部头缺失 → 返回 None（回退共享令牌）。任一头缺失或校验失败 → 401/409。
    """
    import hashlib
    import hmac
    did = request.headers.get("X-Device-Id")
    ts = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    sig = request.headers.get("X-Signature")
    if not any([did, ts, nonce, sig]):
        return None
    if not (did and ts and nonce and sig):
        raise HTTPException(401, "device signature headers incomplete")
    key = store.device_hash(did)
    if not key:
        raise HTTPException(401, "unknown or revoked device")
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.datetime.now(t.tzinfo) if t.tzinfo else datetime.datetime.now()
        if abs((now - t).total_seconds()) > 300:
            raise HTTPException(401, "timestamp skew too large")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "bad X-Timestamp")
    body_hash = hashlib.sha256(body or b"").hexdigest()
    canonical = "\n".join([ts, nonce, request.method, request.url.path, body_hash])
    want = hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, sig):
        raise HTTPException(401, "bad signature")
    if not store.use_nonce(nonce, did):
        raise HTTPException(409, "replay detected (nonce reused)")
    store.audit("device:" + did, "write", request.url.path)
    return did


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
async def sensor(request: Request, req: SensorReq):
    body = await request.body()
    if _verify_device(request, body) is None:
        _require_sensor(request)
    ip = request.client.host if request.client else "global"
    _rate_limit(ip, limit=int(os.environ.get("SENSOR_RPM", "120")))
    accepted, n = store.add_sensor([_valid_sensor(req)])
    return {"status": "ok", "accepted": accepted, "count": n, "dedup": accepted == 0}


@app.post("/api/sensor/batch")
async def sensor_batch(request: Request, req: SensorBatch):
    body = await request.body()
    if _verify_device(request, body) is None:
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
def refresh(request: Request, background: BackgroundTasks, fetch: bool = True, full: bool = False):
    _require_admin(request)
    background.add_task(_refresh, fetch, not full)
    return {"status": "scheduled", "fetch": fetch, "light": not full}


# ---- 定时任务：每日 06:00 全量 + 每小时轻量刷新（若有 apscheduler）----
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _sched = BackgroundScheduler(timezone="Asia/Shanghai")
    _sched.add_job(lambda: _refresh(True, light=False), "cron", hour=6, minute=0, id="daily_refresh")
    _sched.add_job(lambda: _refresh(True, light=True), "cron", minute="*/10", id="refresh_10m",
                   replace_existing=True)
    # 预测验证归档（每 6 小时）
    _sched.add_job(lambda: _run_verify(60), "cron", hour="1,7,13,19", minute=35, id="verify_6h",
                   replace_existing=True)
    # 告警检查与通知（每 30 分钟）
    _sched.add_job(lambda: _notify_alerts(), "cron", minute="5,35", id="alerts_30m",
                   replace_existing=True)
    _sched.start()
    print("[serve] 已启用定时任务（刷新 3h / 验证 6h / 告警 30m）")
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
    """提前期 + 多年春采季真实误差（权威在线归档）。优先返回已入库的最新验证。"""
    lv = store.latest_verification()
    if lv and isinstance(lv.get("payload"), str):
        try:
            data = json.loads(lv["payload"])
            data["_meta"] = {"generated": lv.get("generated"), "build": lv.get("build"), "sha256": lv.get("sha256")}
            return JSONResponse(data)
        except Exception:  # noqa: BLE001
            pass
    if not os.path.exists(VERIFY_JSON):
        return {"status": "pending", "note": "调用 POST /api/forecast/verify/refresh 生成"}
    return JSONResponse(json.load(open(VERIFY_JSON, encoding="utf-8")))


@app.get("/api/forecast/verify/history")
def forecast_verify_history(limit: int = 10):
    """验证运行历史（把"预测验证"纳入数据血缘）。"""
    return {"count": len(store.list_verifications(limit)), "runs": store.list_verifications(limit)}


def _run_verify(days=60):
    try:
        import hashlib
        import forecast_verify as fv
        _saved = sys.argv
        sys.argv = ["forecast_verify", "--days", str(days)]
        try:
            fv.main()
        finally:
            sys.argv = _saved
        p = VERIFY_JSON
        if os.path.exists(p):
            raw = open(p, "rb").read()
            data = json.loads(raw.decode("utf-8"))
            summary = {"lead_tmin_mae": {str(r["lead"]): r["tmin_mae"] for r in data.get("leads", [])},
                       "spring_pooled": (data.get("spring", {}) or {}).get("pooled"),
                       "years": (data.get("spring", {}) or {}).get("years")}
            store.add_verification(season.now().strftime("%Y-%m-%d %H:%M:%S"),
                                   (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:12],
                                   hashlib.sha256(raw).hexdigest()[:16], summary, raw.decode("utf-8"))
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        print("[verify] run failed:", e)
        return {"status": "error", "error": repr(e)}


@app.post("/api/forecast/verify/refresh")
def forecast_verify_refresh(request: Request, background: BackgroundTasks, days: int = 60):
    _require_admin(request)
    background.add_task(_run_verify, days)
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
async def outcome(request: Request, req: OutcomeReq):
    body = await request.body()
    if _verify_device(request, body) is None:
        _require_sensor(request)   # 设备令牌/签名 或 传感器令牌
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
def _pct(arr, q):
    a = sorted(arr)
    if not a:
        return None
    i = min(len(a) - 1, int(round(q * (len(a) - 1))))
    return round(a[i], 1)


@app.get("/api/metrics")
def metrics(request: Request):
    _require_admin(request)
    avg = (_METRICS["latency_ms_sum"] / _METRICS["total"]) if _METRICS["total"] else 0
    fr = _freshness() if os.path.exists(DATA_JSON) else {}
    return {"requests": _METRICS["total"], "errors_5xx": _METRICS["errors"],
            "latency_avg_ms": round(avg, 1), "latency_max_ms": round(_METRICS["latency_max_ms"], 1),
            "latency_p50_ms": _pct(_METRICS["lat"], 0.50), "latency_p95_ms": _pct(_METRICS["lat"], 0.95),
            "latency_p99_ms": _pct(_METRICS["lat"], 0.99),
            "cold_p95_ms": _pct(_METRICS["cold"], 0.95), "hot_p95_ms": _pct(_METRICS["hot"], 0.95),
            "uptime_s": round(_time.time() - _BOOT_TS, 1), "by_path": _METRICS["by_path"],
            "data_age_minutes": fr.get("age_minutes"), "data_stale": fr.get("stale"),
            "refresh": fr.get("refresh"), "build": fr.get("build"),
            "llm_usage": _llm_usage, "llm_daily_budget": LLM_DAILY_BUDGET,
            "sensor_count": store.sensor_count(), "device_active": store.device_count(),
            "versions": store.version_count(), "outcomes": store.outcome_count(),
            "verifications": len(store.list_verifications(1)) if store.version_count() else 0,
            "db": store.db_info()}


@app.get("/api/persistence")
def persistence():
    """持久化自检（公开只读，仅计数/后端类型）：跨重部署保留证据与所需配置。"""
    info = store.db_info()
    counts = {"versions": store.version_count(), "outcomes": store.outcome_count(),
              "devices": store.device_count(active_only=False), "audit": len(store.list_audit(1)),
              "verifications": len(store.list_verifications(1)) if True else 0,
              "reports": len(store.list_reports(1)), "sensors": store.sensor_count()}
    external = bool(os.environ.get("DATABASE_URL"))
    return {"db": info, "counts": counts, "external_configured": external,
            "uptime_s": round(_time.time() - _BOOT_TS, 1),
            "retention_hint": ("已配置外部存储（DATABASE_URL）" if external else
                               "未配置外部存储：Render 临时盘在重部署后可能清零；请挂载持久卷或托管数据库并设置 DATABASE_URL")}


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


# ---- 发布一致性自检 + 告警（第五轮 P0） ----
CRITICAL_ROUTES = ["/api/health", "/api/summary", "/api/days", "/api/ask", "/api/realtime",
                   "/api/data/versions", "/api/forecast/verify", "/api/updates", "/api/ready", "/api/alerts"]


def _api_routes():
    return sorted({getattr(r, "path", "") for r in app.routes if str(getattr(r, "path", "")).startswith("/api/")})


@app.get("/api/ready")
def ready():
    """发布就绪自检：build + 路由完整 + 数据可用 + 非陈旧 + 血缘/刷新状态。"""
    has_data = os.path.exists(DATA_JSON)
    fr = _freshness() if has_data else {}
    routes = _api_routes()
    missing = [p for p in CRITICAL_ROUTES if p not in routes]
    lin = _lineage_ok()
    rs = store.get_refresh_state()
    refresh_ok = rs.get("status") not in ("unknown", "error")
    ran = bool(_COMPARE.get("result"))
    cmp = _COMPARE["result"] if ran else {"cached": False}
    compare_ok = ran and ("error" not in cmp) and (cmp.get("changed") is not True)
    service_ready = bool(has_data and not missing)
    decision_ready = bool(service_ready and (fr.get("stale") is not True) and lin and refresh_ok and compare_ok)
    warnings = []
    if not has_data:
        warnings.append("no_data")
    warnings += [f"missing:{m}" for m in missing]
    if fr.get("stale"):
        warnings.append("stale")
    if not lin:
        warnings.append("no_lineage")
    if not refresh_ok:
        warnings.append("refresh_" + str(rs.get("status")))
    if not ran:
        warnings.append("compare_not_run")
    elif "error" in cmp:
        warnings.append("compare_failed")
    elif cmp.get("changed"):
        warnings.append("forecast_drift")
    return {"ready": decision_ready, "service_ready": service_ready, "decision_ready": decision_ready,
            "build": (os.environ.get("RENDER_GIT_COMMIT", "") or "")[:12],
            "route_count": len(routes), "critical_total": len(CRITICAL_ROUTES),
            "missing_critical": missing, "data_ready": has_data,
            "age_minutes": fr.get("age_minutes"), "stale": fr.get("stale"),
            "data_fresh": fr.get("stale") is not True,
            "lineage_ok": lin, "refresh_ok": refresh_ok, "compare": cmp, "refresh": rs,
            "warnings": warnings,
            "server_time": season.now().isoformat(timespec="seconds")}


def _collect_alerts():
    out = []
    try:
        fr = _freshness() if os.path.exists(DATA_JSON) else {}
        if fr.get("stale"):
            out.append({"level": "warn", "code": "data_stale",
                        "msg": f"数据约 {fr.get('age_minutes')} 分钟前获取，可能已过期"})
        rs = store.get_refresh_state()
        if rs.get("status") == "error":
            out.append({"level": "error", "code": "refresh_failed", "msg": str(rs.get("error"))[:160]})
        if _METRICS["errors"] > 0:
            out.append({"level": "warn", "code": "server_error", "msg": f"5xx 累计 {_METRICS['errors']}"})
        if _llm_usage["count"] >= LLM_DAILY_BUDGET:
            out.append({"level": "warn", "code": "llm_budget", "msg": "LLM 每日预算已用尽"})
        if store.sensor_count() == 0:
            out.append({"level": "info", "code": "no_sensors", "msg": "尚未接入现场传感器"})
        if store.version_count() == 0:
            out.append({"level": "info", "code": "no_versions", "msg": "暂无数据版本快照"})
        cmp = _COMPARE.get("result") or {}
        if cmp.get("changed"):
            out.append({"level": "warn", "code": "forecast_drift",
                        "msg": f"上游预报与本地快照差异较大：ΔTmax {cmp.get('max_tmax_delta')}℃ / "
                               f"Δ降水 {cmp.get('max_precip_delta')}mm（可能已过期）"})
        elif "error" in cmp:
            out.append({"level": "info", "code": "compare_failed",
                        "msg": "上游漂移检测暂不可用（如限流）；建议手动核验最新预报"})
    except Exception as e:  # noqa: BLE001
        out.append({"level": "error", "code": "alerts_error", "msg": repr(e)})
    return out


def _alert_text(payload):
    site = payload.get("site", "TeaWindow")
    t = payload.get("server_time", "")
    new = payload.get("new") or []
    active = payload.get("active") or []
    lines = [f"【{site}】告警通知 {t}".rstrip(),
             "新增: " + (", ".join(new) if new else "无"),
             "当前: " + (", ".join(active) if active else "无")]
    for a in payload.get("alerts") or []:
        if a.get("level") in ("warn", "error"):
            lines.append(f"- [{a.get('level')}] {a.get('code')}: {a.get('msg', '')}")
    return "\n".join(lines)


def _push_webhook(payload):
    """按渠道格式化并推送。ALERT_WEBHOOK_KIND: generic(默认)/slack/feishu/dingtalk。"""
    if not ALERT_WEBHOOK_URL:
        return {"sent": False, "reason": "ALERT_WEBHOOK_URL 未配置"}
    kind = (os.environ.get("ALERT_WEBHOOK_KIND") or "generic").lower()
    try:
        import requests
        url, body = ALERT_WEBHOOK_URL, payload
        if kind == "slack":
            body = {"text": _alert_text(payload)}
        elif kind == "feishu":
            body = {"msg_type": "text", "content": {"text": _alert_text(payload)}}
        elif kind == "dingtalk":
            body = {"msgtype": "text", "text": {"content": _alert_text(payload)}}
            secret = os.environ.get("ALERT_WEBHOOK_SECRET", "")
            if secret:  # 钉钉加签
                import base64, hashlib, hmac, time as _t, urllib.parse
                ts = str(round(_t.time() * 1000))
                string_to_sign = f"{ts}\n{secret}"
                sign = urllib.parse.quote_plus(base64.b64encode(
                    hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()))
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}timestamp={ts}&sign={sign}"
        r = requests.post(url, json=body, timeout=15)
        ok = r.status_code < 400
        detail = str(r.status_code)
        try:  # 钉钉/飞书 用 HTTP 200 + errcode 表达失败
            jj = r.json()
            if isinstance(jj, dict) and jj.get("errcode") not in (None, 0):
                ok, detail = False, f"{r.status_code} errcode={jj.get('errcode')} {jj.get('errmsg', '')}"
        except Exception:  # noqa: BLE001
            pass
        return {"sent": ok, "status": r.status_code, "kind": kind, "detail": detail}
    except Exception as e:  # noqa: BLE001
        return {"sent": False, "reason": repr(e)}


def _notify_alerts(force=False):
    """告警变化时推送到 webhook（避免重复刷屏）。"""
    cur = _collect_alerts()
    codes = {a["code"] for a in cur if a["level"] in ("warn", "error")}
    prev = set(store.get_alerts_state().get("codes") or [])
    if force or codes - prev:      # 新增/变化才推送
        res = _push_webhook({"site": "梅家坞 TeaWindow",
                             "server_time": season.now().isoformat(timespec="seconds"),
                             "new": sorted(codes - prev), "active": sorted(codes),
                             "alerts": cur})
        store.set_alerts_state(codes)
        store.add_alert_delivery(sorted(codes - prev), bool(res.get("sent")),
                                 str(res.get("reason") or res.get("detail") or res.get("status") or ""))
        return {"notified": True, "new": sorted(codes - prev), **res}
    store.set_alerts_state(codes)
    return {"notified": False, "reason": "no_change", "active": sorted(codes)}


@app.get("/api/alerts")
def alerts():
    """规则化告警（公开只读，仅状态码/级别，不含隐私）。"""
    cur = _collect_alerts()
    return {"alerts": cur, "count": len(cur), "server_time": season.now().isoformat(timespec="seconds"),
            "webhook_configured": bool(ALERT_WEBHOOK_URL),
            "webhook_kind": (os.environ.get("ALERT_WEBHOOK_KIND") or "generic").lower(),
            "notified": store.get_alerts_state(),
            "last_delivery": store.last_alert_delivery()}


@app.post("/api/alerts/test")
def alerts_test(request: Request):
    _require_admin(request)
    return _notify_alerts(force=True)


@app.post("/api/alerts/echo")
async def alerts_echo(request: Request):
    """Webhook 回环自测端点：接收并记录投递，用于验证 HTTP 送达链路（真实渠道替换 URL 即可）。"""
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except Exception:  # noqa: BLE001
        payload = {}
    nc = payload.get("new") or []
    store.add_alert_delivery(nc, True, "echo received")
    return {"ok": True, "received_new": nc, "received_active": payload.get("active") or [],
            "server_time": season.now().isoformat(timespec="seconds")}


@app.get("/api/terrain")
def terrain_api():
    """地块级地形风险图数据（网格 + 高风险清单；由 src/terrain_map.py 生成）。"""
    p = os.path.join(WEB, "terrain_grid.json")
    if not os.path.exists(p):
        raise HTTPException(404, "terrain map not generated; run python src/terrain_map.py")
    with open(p, encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.get("/api/forecast/compare")
def forecast_compare(request: Request):
    """change-warning：本地快照 vs 上游最新逐日预报的差异（缓存 30 分钟）。"""
    ip = request.client.host if request.client else "global"
    _rate_limit("cmp:" + ip, limit=int(os.environ.get("COMPARE_RPM", "20")))
    return _compare_upstream()


# 静态站点挂到最后，"/" 作为兜底（API 路由优先）
if os.path.isdir(WEB):
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8000, reload=False)
