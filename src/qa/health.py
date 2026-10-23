"""数据可靠性体检（确定性部分）。

StartLux 能判断"答案是否被证据支持"，但"数据本身是否可靠"更适合用可复现的规则：
新鲜度、日期空洞、上游漂移、血缘完整性、刷新状态。两者结合才是闭环的第一环。

返回 score ∈ [0,1] 与布尔标记；任何异常都降级为"不确定"，不抛错。
"""
from __future__ import annotations

import datetime


def _parse(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts))
    except Exception:  # noqa: BLE001
        return None


def assess(meta, days, refresh=None, compare=None, stale_minutes=120, now=None):
    meta = meta or {}
    refresh = refresh or {}
    compare = compare or {}
    days = days or []
    now = now or datetime.datetime.now()

    # 1) 新鲜度
    fetched = _parse(meta.get("fetched_at") or meta.get("updated"))
    age_min = None
    if fetched is not None:
        if fetched.tzinfo is not None and now.tzinfo is None:
            fetched = fetched.replace(tzinfo=None)
        age_min = max(0.0, (now - fetched).total_seconds() / 60.0)
    fresh = bool(age_min is not None and age_min <= stale_minutes)

    # 2) 日期空洞（允许首尾之外无缺口）
    gap_free, gaps = True, []
    try:
        ds = sorted(datetime.date.fromisoformat(str(d.get("date"))) for d in days if d.get("date"))
        for a, b in zip(ds, ds[1:]):
            if (b - a).days > 1:
                gap_free = False
                gaps.append(f"{a}→{b}")
    except Exception:  # noqa: BLE001
        gap_free = False

    # 3) 上游漂移（serve 的 compare 结果；无结果视为未知而非失败）
    changed = compare.get("changed")
    drift_ok = (changed is not True)

    # 4) 血缘 / 刷新状态
    lineage_ok = bool(meta.get("fetched_at") or meta.get("updated"))
    refresh_ok = refresh.get("status") not in ("error", "unknown")

    checks = {"fresh": fresh, "gap_free": gap_free, "drift_ok": drift_ok,
              "lineage_ok": lineage_ok, "refresh_ok": refresh_ok}
    score = sum(1 for v in checks.values() if v) / len(checks)
    critical = sum(1 for v in (fresh, gap_free, drift_ok, refresh_ok) if not v)
    verdict = "unreliable" if critical >= 2 else ("review" if critical == 1 or score < 0.8 else "ok")

    notes = []
    if not fresh:
        notes.append(f"数据 {age_min:.0f} 分钟未更新（阈值 {stale_minutes}）" if age_min else "缺少数据时间")
    if not gap_free:
        notes.append("日期存在空洞：" + "、".join(gaps[:3]))
    if not drift_ok:
        notes.append(f"上游漂移偏大（ΔTmax {compare.get('max_tmax_delta')}℃ / ΔP {compare.get('max_precip_delta')}mm）")
    if not refresh_ok:
        notes.append("刷新状态异常：" + str(refresh.get("status")))
    if not lineage_ok:
        notes.append("缺少数据血缘")

    return {"score": round(score, 3), "checks": checks, "age_minutes": None if age_min is None else round(age_min, 1),
            "notes": notes, "verdict": verdict}
