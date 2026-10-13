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

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from fastapi import FastAPI, HTTPException, BackgroundTasks  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import llm_advice  # noqa: E402  (触发 .env 加载)

WEB = os.path.join(ROOT, "web")
DATA_JSON = os.path.join(WEB, "data.json")

app = FastAPI(title="TeaWindow API", version="1.0",
              description="梅家坞龙井复合气候风险与采摘窗口决策助手")

_refresh_lock = threading.Lock()
_advice_cache = {}


def _load():
    if not os.path.exists(DATA_JSON):
        raise HTTPException(503, "数据未就绪，请先运行 pipeline 或调用 /api/refresh")
    with open(DATA_JSON, encoding="utf-8") as f:
        return json.load(f)


def _cur_day(days):
    """今天对应的一天：优先日期==今天；否则最近历史日；否则最后一天。"""
    today = datetime.date.today().isoformat()
    m = [d for d in days if d["date"] == today]
    if m:
        return m[0]
    past = [d for d in days if d["date"] <= today]
    return past[-1] if past else days[-1]


def _refresh(do_fetch=True):
    if not _refresh_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        import pipeline
        pipeline.run(do_fetch=do_fetch, do_ndvi=do_fetch, do_figs=False)
        _advice_cache.clear()
        return {"status": "ok"}
    finally:
        _refresh_lock.release()


@app.get("/api/health")
def health():
    return {"status": "ok", "data_ready": os.path.exists(DATA_JSON),
            "has_llm_key": bool(os.environ.get("DEEPSEEK_API_KEY"))}


@app.get("/api/overview")
def overview():
    return JSONResponse(_load())


@app.get("/api/summary")
def summary():
    d = _load()
    days = d["days"]
    forecast = [x for x in days if x["source"] == "forecast"]
    n7 = forecast[:7]
    maxrisk = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else None
    cur = _cur_day(days)
    hist = [x for x in days if x["source"] == "history"]
    return {
        "updated": d["meta"]["updated"],
        "current": {"date": cur["date"], "risk_level": cur["risk_level"],
                    "risk_R": cur["risk_R"], "suitability": cur["suitability"]} if cur else None,
        "next7_max": {"date": maxrisk["date"], "risk_level": maxrisk["risk_level"],
                      "risk_R": maxrisk["risk_R"]} if maxrisk else None,
        "pick_window": d.get("pick_window", []),
        "metrics": d.get("metrics", {}).get("ml", {}),
    }


@app.get("/api/days")
def days(scope: str = "recent"):
    d = _load()
    if scope == "forecast":
        return {"days": [x for x in d["days"] if x["source"] == "forecast"]}
    if scope == "history":
        return {"days": [x for x in d["days"] if x["source"] == "history"]}
    return {"days": d["days"]}


@app.get("/api/advice")
def advice(date: str):
    if date in _advice_cache:
        return _advice_cache[date]
    d = _load()
    row = next((x for x in d["days"] if x["date"] == date), None)
    if row is None:
        raise HTTPException(404, f"未找到日期 {date}")
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
    return {
        "current": ({"date": cur["date"], "risk_level": cur.get("risk_level"),
                     "risk_R": cur.get("risk_R"), "suitability": cur.get("suitability")} if cur else None),
        "next7_max": ({"date": mx["date"], "risk_level": mx.get("risk_level"),
                       "risk_R": mx.get("risk_R")} if mx else None),
        "pick_window": d.get("pick_window", []),
        "best_pick_day": dec.get("best_pick_day"),
        "schedule": [{"date": s["date"], "plots": [p["name"] for p in s["plots"]]} for s in sch],
        "metrics_auc": (d.get("metrics", {}).get("ml", {}) or {}).get("auc"),
        "value": d.get("value"),
    }


class AskReq(BaseModel):
    question: str
    engine: str = "own"   # own=自研引擎(默认)；llm=DeepSeek 可选增强
    history: list = []    # 多轮上下文：[{role:"user"/"assistant", content: "..."}]


def _ask(q, engine, history=None):
    if engine == "llm":
        r = llm_advice.chat(q, _context())
        r.setdefault("engine", "deepseek-chat")
        return r
    from qa import engine as qa_engine
    return qa_engine.answer(q, _context(), history or [])


@app.post("/api/ask")
def ask(req: AskReq):
    return _ask(req.question, req.engine, req.history)


@app.get("/api/ask")
def ask_get(q: str, engine: str = "own"):
    return _ask(q, engine, [])


# ---- 众包物候上报（N4）----
CROWD = os.path.join(ROOT, "data", "processed", "crowd.jsonl")


class ReportReq(BaseModel):
    date: str
    plot: str = ""
    kind: str = ""   # 开采 / 受冻 / 灼伤 / 其他
    note: str = ""


@app.post("/api/report")
def report(req: ReportReq):
    import datetime as _dt
    os.makedirs(os.path.dirname(CROWD), exist_ok=True)
    rec = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "date": req.date,
           "plot": req.plot, "kind": req.kind, "note": req.note}
    with open(CROWD, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    n = sum(1 for _ in open(CROWD, encoding="utf-8"))
    return {"status": "ok", "count": n}


@app.get("/api/reports")
def reports():
    if not os.path.exists(CROWD):
        return {"count": 0, "items": []}
    items = [json.loads(l) for l in open(CROWD, encoding="utf-8") if l.strip()]
    return {"count": len(items), "items": items[-50:]}


@app.post("/api/refresh")
def refresh(background: BackgroundTasks, fetch: bool = True):
    background.add_task(_refresh, fetch)
    return {"status": "scheduled", "fetch": fetch}


# ---- 定时任务：每日 06:00 刷新（若有 apscheduler）----
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _sched = BackgroundScheduler(timezone="Asia/Shanghai")
    _sched.add_job(lambda: _refresh(True), "cron", hour=6, minute=0, id="daily_refresh")
    _sched.start()
    print("[serve] 已启用每日 06:00 定时刷新")
except Exception as e:  # noqa: BLE001
    print("[serve] 未启用定时任务:", e)


@app.on_event("startup")
def _startup():
    if not os.path.exists(DATA_JSON):
        print("[serve] 首次启动，生成数据 ...")
        _refresh(True)


# 静态站点挂到最后，"/" 作为兜底（API 路由优先）
if os.path.isdir(WEB):
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8000, reload=False)
