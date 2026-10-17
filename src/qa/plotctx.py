"""
地块上下文：从问题里解析 "地块(lon, lat …)"，用 terrain_grid.json + 当日预报下推，
供问答把"海拔/坡度/坡向 + 下推 Tmin/Tmax + R"写进来源链（来源可追溯）。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB = os.path.join(ROOT, "web")
_GRID = None


def _grid():
    global _GRID
    if _GRID is None:
        p = os.path.join(WEB, "terrain_grid.json")
        if not os.path.exists(p):
            _GRID = {}
        else:
            with open(p, encoding="utf-8") as f:
                _GRID = json.load(f)
    return _GRID


def _cls(v):
    return "极高" if v >= 0.75 else ("高" if v >= 0.6 else ("中" if v >= 0.4 else "低"))


def parse(q):
    """从问题文本解析 (lon, lat)；支持 "地块(120.1, 30.2 …)" 或裸经纬。"""
    q = q or ""
    m = re.search(r"地块\s*[（(]\s*(\d{2,3}\.\d+)\s*[,，]\s*(\d{2}\.\d+)", q)
    if not m:
        m = re.search(r"(\d{3}\.\d{3,})[,\s]+(\d{2}\.\d{3,})", q)
    if not m:
        return None
    try:
        lon, lat = float(m.group(1)), float(m.group(2))
    except Exception:  # noqa: BLE001
        return None
    if not (119 <= lon <= 121 and 29 <= lat <= 31):
        return None
    return lon, lat


def lookup(lon, lat, data):
    """返回该点上下文（地形 + 当日下推），无网格时返回 None。"""
    g = _grid()
    cells = g.get("cells") or []
    if not cells:
        return None
    bb = g.get("bbox") or [0, 0, 0, 0]
    if not (bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]):
        return {"out_of_aoi": True, "lon": lon, "lat": lat}
    best, bd = None, 1e9
    for c in cells:
        d = (c.get("lon", 0) - lon) ** 2 + (c.get("lat", 0) - lat) ** 2
        if d < bd:
            bd, best = d, c
    if not best:
        return None
    fc = [x for x in (data or {}).get("days", []) if x.get("source") == "forecast"]
    day = fc[0] if fc else {}
    out = {"lon": best.get("lon"), "lat": best.get("lat"), "elev_m": best.get("elev"),
           "slope_deg": best.get("slope"), "aspect_deg": best.get("aspect"),
           "date": day.get("date"), "tmin": None, "tmax": None, "R": None, "level": None}
    if day.get("tmin") is not None and best.get("dtmin") is not None:
        tmin = round(float(day["tmin"]) + float(best["dtmin"]), 1)
        tmax = round(float(day.get("tmax") or 30) + float(best.get("dtmax") or 0), 1)
        fs = max(0.0, min(1.0, (2.0 - tmin) / 4.0))
        hs = max(0.0, min(1.0, (tmax - 33.0) / 5.0))
        ds = float(best.get("drought") or 0) * 0.6
        R = max(fs, hs, ds)
        out.update({"tmin": tmin, "tmax": tmax, "R": round(R, 2), "level": _cls(R)})
    return out


def chain_text(ctx):
    if not ctx:
        return ""
    if ctx.get("out_of_aoi"):
        return f"地块上下文: {ctx['lon']},{ctx['lat']} 不在梅家坞茶园 AOI 内"
    s = f"地块上下文: {ctx.get('lon')},{ctx.get('lat')} · 海拔{ctx.get('elev_m')}m · 坡向{ctx.get('aspect_deg')}°"
    if ctx.get("tmin") is not None:
        s += f" · 下推 Tmin {ctx['tmin']}℃/Tmax {ctx['tmax']}℃ · R={ctx['R']}（{ctx['level']}）"
    return s


def _hazards(tmin, tmax, drought, dry_run=0, deficit=0):
    fs = max(0.0, min(1.0, (2.0 - tmin) / 4.0))
    hs = max(0.0, min(1.0, (tmax - 33.0) / 5.0))
    # 干旱项随当日"连续少雨/水分亏缺"变化（地形干燥度做权重）
    dryness = max(min(float(dry_run or 0) / 10.0, 1.0), min(max(float(deficit or 0), 0) / 45.0, 1.0))
    ds = dryness * (0.6 + 0.4 * float(drought or 0))
    R = max(fs, hs, ds)
    return round(R, 2), _cls(R)


def series(lon, lat, data, n=3, scope="next"):
    """地块级多日时序（下推）：返回 [(date, tmin, tmax, precip, R, level)]。"""
    g = _grid()
    cells = g.get("cells") or []
    if not cells:
        return []
    best, bd = None, 1e9
    for c in cells:
        d = (c.get("lon", 0) - lon) ** 2 + (c.get("lat", 0) - lat) ** 2
        if d < bd:
            bd, best = d, c
    if not best or best.get("dtmin") is None:
        return []
    days = (data or {}).get("days", [])
    fc = [x for x in days if x.get("source") == "forecast"]
    hist = [x for x in days if x.get("source") == "history"]
    if scope == "past":
        sub = hist[-n:]
    elif scope == "all":
        sub = (hist[-n:] if scope == "past" else []) + fc[:n]
    else:
        sub = fc[:n]
    out = []
    for d in sub:
        tmin = round(float(d.get("tmin") or 0) + float(best["dtmin"]), 1)
        tmax = round(float(d.get("tmax") or 30) + float(best.get("dtmax") or 0), 1)
        R, level = _hazards(tmin, tmax, best.get("drought"), d.get("dry_run"), d.get("deficit"))
        out.append({"date": d.get("date"), "tmin": tmin, "tmax": tmax,
                    "precip": d.get("precip"), "R": R, "level": level,
                    "site_risk": d.get("risk_level")})
    return out
