"""
轻量持久化：SQLite 存储众包上报与传感器观测（替代直接追加 JSONL）。
- 幂等：传感器以 (station_id, ts) 唯一，重复/重放不重复入库。
- 记录服务器接收时间 received 与质量校验。
- 说明：免费托管磁盘本身可能短暂，生产应接外部数据库；本模块保证单实例内的持久与去重。
"""
import json
import os
import sqlite3
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("TW_DB", os.path.join(ROOT, "data", "teawindow.db"))
_LOCK = threading.Lock()
_conn = None

SENSOR_FIELDS = ("temp", "rh", "soil_moisture", "soil_temp", "precip", "wind", "light", "vpd")


def _db():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, date TEXT, plot TEXT, kind TEXT, note TEXT)""")
        cols = ",".join(f"{f} REAL" for f in SENSOR_FIELDS)
        _conn.execute(f"""CREATE TABLE IF NOT EXISTS sensor(
            station_id TEXT NOT NULL, ts TEXT NOT NULL, received TEXT, note TEXT, {cols},
            PRIMARY KEY(station_id, ts))""")
        _conn.commit()
    return _conn


def add_report(rec):
    with _LOCK:
        c = _db()
        c.execute("INSERT INTO reports(ts,date,plot,kind,note) VALUES(?,?,?,?,?)",
                  (rec.get("ts"), rec.get("date"), rec.get("plot"), rec.get("kind"), rec.get("note")))
        c.commit()
        return c.execute("SELECT COUNT(*) FROM reports").fetchone()[0]


def list_reports(limit=50):
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT ts,date,plot,kind,note FROM reports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    keys = ("ts", "date", "plot", "kind", "note")
    return [dict(zip(keys, r)) for r in rows]


def add_sensor(recs):
    """recs: list[dict]（含 station_id, ts, received 与若干测量）。返回 (accepted, count)。"""
    accepted = 0
    with _LOCK:
        c = _db()
        for r in recs:
            cols = ["station_id", "ts", "received", "note"] + list(SENSOR_FIELDS)
            vals = [r.get("station_id"), r.get("ts"), r.get("received"), r.get("note")] + [r.get(f) for f in SENSOR_FIELDS]
            ph = ",".join("?" for _ in cols)
            cur = c.execute(f"INSERT OR IGNORE INTO sensor({','.join(cols)}) VALUES({ph})", vals)
            accepted += cur.rowcount
        c.commit()
        n = c.execute("SELECT COUNT(*) FROM sensor").fetchone()[0]
    return accepted, n


def sensor_latest():
    """各站最新一条（按 ts 最大）。返回 {station_id: {...}}。"""
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT * FROM sensor").fetchall()
        col = [d[0] for d in c.execute("SELECT * FROM sensor LIMIT 1").description] if rows else []
    latest = {}
    for r in rows:
        rec = dict(zip(col, r))
        sid = rec["station_id"]
        if sid not in latest or str(rec.get("ts")) > str(latest[sid].get("ts")):
            latest[sid] = rec
    return latest


def sensor_count():
    with _LOCK:
        return _db().execute("SELECT COUNT(*) FROM sensor").fetchone()[0]


def sensor_items(station_id="", limit=200):
    with _LOCK:
        c = _db()
        if station_id:
            rows = c.execute("SELECT * FROM sensor WHERE station_id=? ORDER BY ts DESC LIMIT ?",
                             (station_id, max(1, min(limit, 500)))).fetchall()
        else:
            rows = c.execute("SELECT * FROM sensor ORDER BY received DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        col = [d[0] for d in c.execute("SELECT * FROM sensor LIMIT 1").description] if rows else []
    return [dict(zip(col, r)) for r in rows]


if __name__ == "__main__":
    print("db:", DB_PATH)
    print("reports:", add_report({"ts": "t", "date": "2026-10-14", "plot": "", "kind": "开采", "note": ""}))
    print("sensor:", add_sensor([{"station_id": "MJW01", "ts": "2026-10-14T08:00:00+08:00", "received": "now", "temp": 16.1}]))
    print("latest:", sensor_latest())