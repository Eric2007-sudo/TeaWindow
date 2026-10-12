"""
遥感模块：获取梅家坞 AOI 的植被信号。
- 真实数据源 A：NASA GIBS WMS 的 MODIS Terra NDVI 8 天合成（约 250m–1km），
  用官方图例把颜色反演为近似 NDVI；受 GIBS 缓存限制，仅覆盖 2025-02 起。
- 真实数据源 B：Element84 Earth Search STAC 查询 Sentinel-2 L2A 场景清单（更高分辨率能力证明）。
输出：data/processed/ndvi.json
说明：颜色→NDVI 为近似反演，仅作相对植被活力指标，非精标定 NDVI（已在报告中声明不确定性）。
"""
import io
import json
import os
import urllib.request
from datetime import date, timedelta

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
AOI = (120.085, 30.205, 120.105, 30.225)  # lon0,lat0,lon1,lat1
UA = {"User-Agent": "TeaWindow/1.0"}
NDVI_MIN, NDVI_MAX = -0.2, 1.0


def _get(url, data=None, headers=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    return urllib.request.urlopen(req, timeout=60).read()


def load_legend():
    b = _get("https://gibs.earthdata.nasa.gov/legends/MODIS_L3_NDVI_H.png")
    a = np.asarray(Image.open(io.BytesIO(b)).convert("RGB"))
    row = a[a.shape[0] // 2].astype(float)
    # 去掉两端空白（近白）确定色条范围
    nonwhite = np.where(row.sum(1) < 730)[0]
    if len(nonwhite) == 0:
        nonwhite = np.arange(len(row))
    x0, x1 = nonwhite[0], nonwhite[-1]
    bar = row[x0:x1 + 1]
    return bar


def color_to_ndvi(bar, rgb):
    d = ((bar - np.asarray(rgb)) ** 2).sum(1)
    x = int(np.argmin(d))
    frac = x / max(1, len(bar) - 1)
    return NDVI_MIN + frac * (NDVI_MAX - NDVI_MIN)


def fetch_ndvi_day(bar, t):
    url = ("https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
           "&LAYERS=MODIS_Terra_NDVI_8Day&STYLES=&FORMAT=image/png&TRANSPARENT=FALSE&HEIGHT=8&WIDTH=8"
           f"&CRS=EPSG:4326&BBOX={AOI[1]},{AOI[0]},{AOI[3]},{AOI[2]}&TIME={t}")
    b = _get(url)
    a = np.asarray(Image.open(io.BytesIO(b)).convert("RGB")).reshape(-1, 3).astype(float)
    if a.sum() < 10:  # 无数据
        return None
    px = a.mean(0)
    return round(color_to_ndvi(bar, px), 3)


def stac_sentinel2(start, end, limit=60):
    body = json.dumps({
        "bbox": list(AOI), "datetime": f"{start}T00:00:00Z/{end}T00:00:00Z",
        "collections": ["sentinel-2-l2a"], "limit": limit,
        "query": {"eo:cloud_cover": {"lt": 40}},
    }).encode()
    try:
        raw = _get("https://earth-search.aws.element84.com/v1/search", data=body,
                   headers={"Content-Type": "application/json"})
        j = json.loads(raw)
        out = []
        for ft in j.get("features", []):
            p = ft["properties"]
            out.append({"id": ft["id"], "date": p.get("datetime", "")[:10],
                        "cloud": round(p.get("eo:cloud_cover", -1), 1)})
        return out
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)}]


def main():
    os.makedirs(PROC, exist_ok=True)
    bar = load_legend()
    start, end = date(2025, 2, 12), date.today()
    series = []
    d = start
    while d <= end:
        try:
            v = fetch_ndvi_day(bar, d.isoformat())
            if v is not None:
                series.append({"date": d.isoformat(), "ndvi": v})
                print(f"  {d} -> {v}")
        except Exception as e:  # noqa: BLE001
            print(f"  {d} ERR {e}")
        d += timedelta(days=8)
    scenes = stac_sentinel2("2025-01-01", date.today().isoformat())
    out = {
        "aoi": {"lon0": AOI[0], "lat0": AOI[1], "lon1": AOI[2], "lat1": AOI[3]},
        "source_modis": "NASA GIBS WMS: MODIS_Terra_NDVI_8Day（颜色反演，近似）",
        "source_sentinel2": "Element84 Earth Search STAC: sentinel-2-l2a（场景清单）",
        "ndvi_range_assumed": [NDVI_MIN, NDVI_MAX],
        "series": series,
        "sentinel2_scenes": scenes[:40],
        "caveat": "GIBS 缓存自 2025-02 起；颜色→NDVI 为近似反演，仅表相对植被活力。",
    }
    with open(os.path.join(PROC, "ndvi.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"NDVI 点数={len(series)}; S2 场景={len(scenes)} -> data/processed/ndvi.json")


if __name__ == "__main__":
    main()
