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

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from fastapi import FastAPI, HTTPException, BackgroundTasks  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

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
    cur = next((x for x in days if x["source"] == "history"), None)
    hist = [x for x in days if x["source"] == "history"]
    if hist:
        cur = hist[-1]
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
