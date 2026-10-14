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
        # 数据版本 / 预报快照（用于提前期误差评估与数据血缘）
        _conn.execute("""CREATE TABLE IF NOT EXISTS data_versions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, model TEXT, gen_time TEXT,
            fetched_at TEXT, lat REAL, lon REAL, raw_sha256 TEXT, n_days INTEGER, build TEXT, note TEXT)""")
        _conn.execute("""CREATE TABLE IF NOT EXISTS forecast_days(
            version_id INTEGER, date TEXT, tmin REAL, tmax REAL, precip REAL, p_frost REAL, p_heat REAL,
            risk_R REAL, risk_level TEXT, PRIMARY KEY(version_id, date))""")
        # 设备级凭证（哈希存储）+ 审计
        _conn.execute("""CREATE TABLE IF NOT EXISTS devices(
            device_id TEXT PRIMARY KEY, token_hash TEXT, created TEXT, revoked INTEGER DEFAULT 0, last_seen TEXT)""")
        _conn.execute("""CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, detail TEXT)""")
        # 田间结果（前瞻性盲测真值）
        _conn.execute("""CREATE TABLE IF NOT EXISTS outcomes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, date TEXT, plot TEXT, kind TEXT,
            area_mu REAL, damage_level TEXT, yield_kg REAL, quality TEXT, note TEXT)""")
        # 刷新任务状态（外部定时/队列可写）
        _conn.execute("""CREATE TABLE IF NOT EXISTS refresh_state(
            k TEXT PRIMARY KEY, ts TEXT, status TEXT, duration_s REAL, error TEXT,
            last_success TEXT, next_planned TEXT)""")
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


# ---------------- 数据版本 / 预报快照（用于提前期误差与血缘） ----------------
def save_snapshot(meta, days):
    """meta: {ts,source,model,gen_time,fetched_at,lat,lon,raw_sha256,build,note}; days: [{date,tmin,tmax,precip,p_frost,p_heat,risk_R,risk_level}]"""
    with _LOCK:
        c = _db()
        cur = c.execute("""INSERT INTO data_versions(ts,source,model,gen_time,fetched_at,lat,lon,raw_sha256,n_days,build,note)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (meta.get("ts"), meta.get("source"), meta.get("model"), meta.get("gen_time"),
                         meta.get("fetched_at"), meta.get("lat"), meta.get("lon"), meta.get("raw_sha256"),
                         len(days), meta.get("build"), meta.get("note")))
        vid = cur.lastrowid
        for d in days:
            c.execute("""INSERT OR REPLACE INTO forecast_days(version_id,date,tmin,tmax,precip,p_frost,p_heat,risk_R,risk_level)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (vid, d.get("date"), d.get("tmin"), d.get("tmax"), d.get("precip"),
                       d.get("p_frost"), d.get("p_heat"), d.get("risk_R"), d.get("risk_level")))
        c.commit()
    return vid


def list_versions(limit=20):
    with _LOCK:
        c = _db()
        rows = c.execute("""SELECT id,ts,source,model,gen_time,fetched_at,lat,lon,raw_sha256,n_days,build
                            FROM data_versions ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 200)),)).fetchall()
    keys = ("id", "ts", "source", "model", "gen_time", "fetched_at", "lat", "lon", "raw_sha256", "n_days", "build")
    return [dict(zip(keys, r)) for r in rows]


def version_days(version_id):
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT date,tmin,tmax,precip,p_frost,p_heat,risk_R,risk_level FROM forecast_days WHERE version_id=?",
                         (version_id,)).fetchall()
    keys = ("date", "tmin", "tmax", "precip", "p_frost", "p_heat", "risk_R", "risk_level")
    return [dict(zip(keys, r)) for r in rows]


def version_count():
    with _LOCK:
        return _db().execute("SELECT COUNT(*) FROM data_versions").fetchone()[0]


# ---------------- 设备级凭证 + 审计 ----------------
def _hash(tok):
    import hashlib
    return hashlib.sha256((tok or "").encode("utf-8")).hexdigest()


def register_device(device_id, token, actor="admin"):
    with _LOCK:
        c = _db()
        c.execute("INSERT OR REPLACE INTO devices(device_id,token_hash,created,revoked,last_seen) VALUES(?,?,?,0,?)",
                  (device_id, _hash(token), datetime_now(), datetime_now()))
        c.commit()
    audit(actor, "device_register", device_id)
    return device_id


def verify_device(token):
    if not token:
        return None
    h = _hash(token)
    with _LOCK:
        c = _db()
        row = c.execute("SELECT device_id FROM devices WHERE token_hash=? AND revoked=0", (h,)).fetchone()
    if row:
        with _LOCK:
            _db().execute("UPDATE devices SET last_seen=? WHERE device_id=?", (datetime_now(), row[0]))
            _db().commit()
        return row[0]
    return None


def revoke_device(device_id, actor="admin"):
    with _LOCK:
        c = _db()
        c.execute("UPDATE devices SET revoked=1 WHERE device_id=?", (device_id,))
        c.commit()
    audit(actor, "device_revoke", device_id)
    return device_id


def device_count(active_only=True):
    with _LOCK:
        c = _db()
        q = "SELECT COUNT(*) FROM devices" + (" WHERE revoked=0" if active_only else "")
        return c.execute(q).fetchone()[0]


def audit(actor, action, detail=""):
    with _LOCK:
        c = _db()
        c.execute("INSERT INTO audit(ts,actor,action,detail) VALUES(?,?,?,?)", (datetime_now(), actor, action, detail))
        c.commit()


def list_audit(limit=100):
    with _LOCK:
        rows = _db().execute("SELECT ts,actor,action,detail FROM audit ORDER BY id DESC LIMIT ?",
                             (max(1, min(limit, 500)),)).fetchall()
    return [dict(zip(("ts", "actor", "action", "detail"), r)) for r in rows]


# ---------------- 田间结果（前瞻性盲测真值） ----------------
OUTCOME_KINDS = {"采摘", "霜冻受灾", "高温灼伤", "连阴雨", "产量", "品质", "其他"}


def add_outcome(rec):
    with _LOCK:
        c = _db()
        c.execute("""INSERT INTO outcomes(ts,date,plot,kind,area_mu,damage_level,yield_kg,quality,note)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  (rec.get("ts"), rec.get("date"), rec.get("plot"), rec.get("kind"), rec.get("area_mu"),
                   rec.get("damage_level"), rec.get("yield_kg"), rec.get("quality"), rec.get("note")))
        c.commit()
        return c.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]


def list_outcomes(limit=100):
    with _LOCK:
        rows = _db().execute("""SELECT ts,date,plot,kind,area_mu,damage_level,yield_kg,quality,note
                                FROM outcomes ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 500)),)).fetchall()
    keys = ("ts", "date", "plot", "kind", "area_mu", "damage_level", "yield_kg", "quality", "note")
    return [dict(zip(keys, r)) for r in rows]


def outcome_count():
    with _LOCK:
        return _db().execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]


# ---------------- 刷新任务状态（供新鲜度闸门/监控） ----------------
def set_refresh_state(status, duration_s=None, error="", next_planned=""):
    with _LOCK:
        c = _db()
        row = c.execute("SELECT last_success FROM refresh_state WHERE k='main'").fetchone()
        last_success = row[0] if row else None
        if status == "ok":
            last_success = datetime_now()
        c.execute("""INSERT OR REPLACE INTO refresh_state(k,ts,status,duration_s,error,last_success,next_planned)
                     VALUES('main',?,?,?,?,?,?)""",
                  (datetime_now(), status, duration_s, (error or "")[:300], last_success, next_planned))
        c.commit()
    return {"status": status, "last_success": last_success}


def get_refresh_state():
    with _LOCK:
        row = _db().execute("SELECT ts,status,duration_s,error,last_success,next_planned FROM refresh_state WHERE k='main'").fetchone()
    if not row:
        return {"status": "unknown", "last_success": None}
    return dict(zip(("ts", "status", "duration_s", "error", "last_success", "next_planned"), row))


# ---------------- 盲测评估：预测快照 × 田间结果（事件级） ----------------
def pilot_evaluate(hazard_kinds=None, risk_threshold=0.5):
    """把"冻结预测快照"与"田间结果"按日期配对，输出事件级混淆矩阵与提前量（可复算）。"""
    hazard_kinds = hazard_kinds or {"霜冻受灾", "高温灼伤", "连阴雨"}
    outcomes = list_outcomes(1000)
    if not outcomes:
        return {"status": "pending", "reason": "no_outcomes", "outcomes": 0, "versions": version_count()}
    event_dates = {o["date"]: o for o in outcomes if o.get("kind") in hazard_kinds and o.get("date")}
    if not event_dates:
        return {"status": "pending", "reason": "no_hazard_outcomes", "outcomes": len(outcomes), "versions": version_count()}
    vers = list_versions(200)
    if not vers:
        return {"status": "pending", "reason": "no_snapshots", "outcomes": len(outcomes), "versions": 0}
    # 以最早覆盖事件日的快照为"预测"（冻结口径）
    today_iso = datetime_now()[:10]
    tp = fp = fn = tn = 0
    leads = []
    samples = []
    # 预测为正的日期集合（取每个快照的 forecast_days）
    pred_pos = {}
    issued = {}
    for v in vers:
        for d in version_days(v["id"]):
            r = d.get("risk_R")
            if r is None:
                continue
            pos = (r >= risk_threshold)
            # 保留最早一次覆盖该日、且在该日之前发布的预测
            if d["date"] not in pred_pos or (v.get("ts") or "") < issued.get(d["date"], "9"):
                pred_pos[d["date"]] = pos
                issued[d["date"]] = v.get("ts") or ""
    all_dates = set(pred_pos) | set(event_dates)
    for day in sorted(all_dates):
        if day > today_iso:
            continue  # 只看已发生（有结果可判定）的日期
        pred = bool(pred_pos.get(day, False))
        actual = day in event_dates
        if pred and actual:
            tp += 1
            try:
                import datetime as _dt
                lead = (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(str(issued.get(day))[:10])).days
                if lead >= 0:
                    leads.append(lead)
            except Exception:  # noqa: BLE001
                pass
        elif pred and not actual:
            fp += 1
        elif (not pred) and actual:
            fn += 1
        else:
            tn += 1
        if day in event_dates:
            samples.append({"date": day, "predicted": pred, "actual": True, "kind": event_dates[day].get("kind")})
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    far = fp / (tp + fp) if (tp + fp) else None
    csi = tp / (tp + fp + fn) if (tp + fp + fn) else None
    import statistics as _st
    return {"status": "ready", "matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "precision": None if prec is None else round(prec, 3),
            "recall": None if rec is None else round(rec, 3),
            "false_alarm_rate": None if far is None else round(far, 3),
            "csi": None if csi is None else round(csi, 3),
            "lead_days_mean": round(_st.mean(leads), 1) if leads else None,
            "n_events": len(event_dates), "n_snapshots": len(vers),
            "samples": samples[:50]}


def datetime_now():
    import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return datetime.datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    print("db:", DB_PATH)
    print("reports:", add_report({"ts": "t", "date": "2026-10-14", "plot": "", "kind": "开采", "note": ""}))
    print("sensor:", add_sensor([{"station_id": "MJW01", "ts": "2026-10-14T08:00:00+08:00", "received": "now", "temp": 16.1}]))
    print("latest:", sensor_latest())