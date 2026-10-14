"""
持久化层：默认 SQLite；支持 `DATABASE_URL`（`sqlite:///…` 指向持久卷；`postgres://…` 走 Postgres 适配）。
- 幂等：传感器以 (station_id, ts) 唯一，重复/重放不重复入库。
- 说明：Postgres 适配为占位符/upsert 翻译层，本机以 SQLite 验证；生产接入 Postgres 前请回归测试。
"""
import json
import os
import re
import sqlite3
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_db():
    url = os.environ.get("DATABASE_URL") or os.environ.get("TW_DB_URL") or ""
    if url.startswith("sqlite:///"):
        p = url[len("sqlite:///"):]
        path = p if os.path.isabs(p) else os.path.join(ROOT, p)
        return path, "sqlite", url
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return None, "postgres", url
    return os.environ.get("TW_DB", os.path.join(ROOT, "data", "teawindow.db")), "sqlite", url


DB_PATH, _DIALECT, _DB_URL = _resolve_db()
_LOCK = threading.Lock()
_conn = None

SENSOR_FIELDS = ("temp", "rh", "soil_moisture", "soil_temp", "precip", "wind", "light", "vpd")
_UPSERT_PK = {"devices": "device_id", "forecast_days": "version_id,date", "refresh_state": "k", "alerts_state": "k"}


def _tr(sql):
    """为 Postgres 翻译占位符与 upsert 语法（SQLite 原样）。"""
    if _DIALECT != "postgres":
        return sql
    s = sql
    if "INSERT OR IGNORE" in s:
        s = s.replace("INSERT OR IGNORE", "INSERT").rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    elif "INSERT OR REPLACE" in s:
        m = re.match(r"\s*INSERT OR REPLACE INTO (\w+)\s*\(([^)]*)\)", s)
        s = s.replace("INSERT OR REPLACE INTO", "INSERT INTO")
        if m:
            tbl, cols = m.group(1), [c.strip() for c in m.group(2).split(",")]
            pk = _UPSERT_PK.get(tbl)
            if pk:
                pks = [x.strip() for x in pk.split(",")]
                sets = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pks)
                s = s.rstrip().rstrip(";") + f" ON CONFLICT ({pk})" + (f" DO UPDATE SET {sets}" if sets else " DO NOTHING")
    return s.replace("?", "%s")


class _Cur:
    def __init__(self, cur):
        self._c = cur
        self.rowcount = getattr(cur, "rowcount", 0)
        self.description = getattr(cur, "description", None)

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()


class _PgConn:
    """psycopg 连接的轻量包装，使既有 `?` 占位符与 `INSERT OR ...` 语法可复用。"""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        cur.execute(_tr(sql), params)
        return _Cur(cur)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def _ddl():
    ai = "BIGSERIAL PRIMARY KEY" if _DIALECT == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    cols = ",".join(f"{f} REAL" for f in SENSOR_FIELDS)
    return [
        f"CREATE TABLE IF NOT EXISTS reports(id {ai}, ts TEXT, date TEXT, plot TEXT, kind TEXT, note TEXT)",
        f"CREATE TABLE IF NOT EXISTS sensor(station_id TEXT NOT NULL, ts TEXT NOT NULL, received TEXT, note TEXT, {cols}, PRIMARY KEY(station_id, ts))",
        f"CREATE TABLE IF NOT EXISTS data_versions(id {ai}, ts TEXT, source TEXT, model TEXT, gen_time TEXT, fetched_at TEXT, lat REAL, lon REAL, raw_sha256 TEXT, n_days INTEGER, build TEXT, note TEXT)",
        "CREATE TABLE IF NOT EXISTS forecast_days(version_id INTEGER, date TEXT, tmin REAL, tmax REAL, precip REAL, p_frost REAL, p_heat REAL, risk_R REAL, risk_level TEXT, PRIMARY KEY(version_id, date))",
        "CREATE TABLE IF NOT EXISTS devices(device_id TEXT PRIMARY KEY, token_hash TEXT, created TEXT, revoked INTEGER DEFAULT 0, last_seen TEXT)",
        f"CREATE TABLE IF NOT EXISTS audit(id {ai}, ts TEXT, actor TEXT, action TEXT, detail TEXT)",
        f"CREATE TABLE IF NOT EXISTS outcomes(id {ai}, ts TEXT, date TEXT, plot TEXT, kind TEXT, area_mu REAL, damage_level TEXT, yield_kg REAL, quality TEXT, note TEXT)",
        "CREATE TABLE IF NOT EXISTS refresh_state(k TEXT PRIMARY KEY, ts TEXT, status TEXT, duration_s REAL, error TEXT, last_success TEXT, next_planned TEXT)",
        f"CREATE TABLE IF NOT EXISTS verifications(id {ai}, ts TEXT, build TEXT, sha256 TEXT, summary TEXT, payload TEXT)",
        "CREATE TABLE IF NOT EXISTS alerts_state(k TEXT PRIMARY KEY, ts TEXT, codes TEXT)",
    ]


def _db():
    global _conn
    if _conn is None:
        if _DIALECT == "postgres":
            try:
                import psycopg  # noqa: PLC0415
                _conn = _PgConn(psycopg.connect(_DB_URL))
            except Exception as e:  # noqa: BLE001
                print("[store] Postgres 不可用，回退 SQLite:", e)
                globals()["_DIALECT"] = "sqlite"
        if _DIALECT != "postgres":
            path = DB_PATH or os.path.join(ROOT, "data", "teawindow.db")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _conn = sqlite3.connect(path, check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
        for stmt in _ddl():
            try:
                _conn.execute(stmt)
            except Exception:  # noqa: BLE001
                pass
        for col, typ in (("upstream_url", "TEXT"), ("params", "TEXT"), ("raw_sha256_full", "TEXT")):
            try:
                _conn.execute(f"ALTER TABLE data_versions ADD COLUMN {col} {typ}")
            except Exception:  # noqa: BLE001
                pass
        _conn.commit()
    return _conn


def db_info():
    return {"dialect": _DIALECT, "url_configured": bool(_DB_URL), "path": DB_PATH}


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
        cur = c.execute("""INSERT INTO data_versions(ts,source,model,gen_time,fetched_at,lat,lon,raw_sha256,n_days,build,note,upstream_url,params,raw_sha256_full)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (meta.get("ts"), meta.get("source"), meta.get("model"), meta.get("gen_time"),
                         meta.get("fetched_at"), meta.get("lat"), meta.get("lon"), meta.get("raw_sha256"),
                         len(days), meta.get("build"), meta.get("note"),
                         meta.get("upstream_url"), meta.get("params"), meta.get("raw_sha256_full")))
        vid = getattr(cur, "lastrowid", None)
        if not vid:
            try:
                vid = c.execute("SELECT MAX(id) FROM data_versions").fetchone()[0]
            except Exception:  # noqa: BLE001
                vid = 0
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
        rows = c.execute("""SELECT id,ts,source,model,gen_time,fetched_at,lat,lon,raw_sha256,n_days,build,upstream_url,params,raw_sha256_full
                            FROM data_versions ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 200)),)).fetchall()
    keys = ("id", "ts", "source", "model", "gen_time", "fetched_at", "lat", "lon", "raw_sha256", "n_days", "build",
            "upstream_url", "params", "raw_sha256_full")
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


# ---------------- 验证运行归档 + 告警通知状态 ----------------
def add_verification(ts, build, sha256, summary, payload):
    with _LOCK:
        c = _db()
        c.execute("INSERT INTO verifications(ts,build,sha256,summary,payload) VALUES(?,?,?,?,?)",
                  (ts, build, sha256, json.dumps(summary, ensure_ascii=False), payload))
        c.commit()
        return c.execute("SELECT COUNT(*) FROM verifications").fetchone()[0]


def list_verifications(limit=20):
    with _LOCK:
        rows = _db().execute("SELECT ts,build,sha256,summary FROM verifications ORDER BY id DESC LIMIT ?",
                             (max(1, min(limit, 200)),)).fetchall()
    out = []
    for ts, build, sha, summary in rows:
        try:
            s = json.loads(summary) if summary else {}
        except Exception:  # noqa: BLE001
            s = {}
        out.append({"ts": ts, "build": build, "sha256": sha, "summary": s})
    return out


def latest_verification():
    with _LOCK:
        row = _db().execute("SELECT ts,build,sha256,summary,payload FROM verifications ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    ts, build, sha, summary, payload = row
    return {"generated": ts, "build": build, "sha256": sha,
            "summary": json.loads(summary) if summary else {}, "payload": payload}


def set_alerts_state(codes):
    with _LOCK:
        c = _db()
        c.execute("INSERT OR REPLACE INTO alerts_state(k,ts,codes) VALUES('main',?,?)",
                  (datetime_now(), json.dumps(sorted(codes), ensure_ascii=False)))
        c.commit()


def get_alerts_state():
    with _LOCK:
        row = _db().execute("SELECT ts,codes FROM alerts_state WHERE k='main'").fetchone()
    if not row:
        return {"ts": None, "codes": []}
    try:
        codes = json.loads(row[1]) if row[1] else []
    except Exception:  # noqa: BLE001
        codes = []
    return {"ts": row[0], "codes": codes}


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