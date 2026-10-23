"""数据可靠性体检的离线测试。"""
import datetime

from qa import health


def _meta(ts):
    return {"fetched_at": ts}


def _days(start, n):
    d0 = datetime.date.fromisoformat(start)
    return [{"date": str(d0 + datetime.timedelta(days=i))} for i in range(n)]


NOW = datetime.datetime(2026, 10, 23, 12, 0)


def test_fresh_gapfree_ok():
    h = health.assess(_meta("2026-10-23 11:30"), _days("2026-10-20", 4),
                      {"status": "ok"}, {"changed": False}, now=NOW)
    assert h["checks"]["fresh"] and h["checks"]["gap_free"]
    assert h["verdict"] == "ok" and h["score"] >= 0.8


def test_stale_and_gap_flagged():
    h = health.assess(_meta("2026-10-23 06:00"), _days("2026-10-20", 2) + _days("2026-10-23", 2),
                      {"status": "ok"}, {"changed": False}, now=NOW)
    assert h["checks"]["fresh"] is False
    assert h["checks"]["gap_free"] is False
    assert h["verdict"] in ("review", "unreliable")
    assert any("空洞" in n for n in h["notes"])


def test_drift_and_refresh_error():
    h = health.assess(_meta("2026-10-23 11:55"), _days("2026-10-22", 2),
                      {"status": "error"}, {"changed": True, "max_tmax_delta": 4.2}, now=NOW)
    assert h["checks"]["drift_ok"] is False
    assert h["checks"]["refresh_ok"] is False
    assert h["verdict"] == "unreliable"
