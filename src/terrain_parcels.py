"""
地块边界叠加（可选）：从 OSM Overpass 拉取梅家坞 AOI 内的园地/农田多边形，输出 web/terrain_parcels.json。
- 仅作"参考边界"（OSM 数据，可能不完整）；不用于任何数值结论。
用法：python src/terrain_parcels.py
"""
import json
import os
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
BBOX = (120.089, 30.207, 120.104, 30.222)          # lon0,lat0,lon1,lat1
UA = {"User-Agent": "TeaWindow/1.0 (climate research; contact: 2302372846@qq.com)"}
PLOTS = [("梅坞溪谷", 120.0961, 30.2139), ("北坡茶园", 120.0985, 30.2160),
         ("村口", 120.0935, 30.2115), ("高处茶园", 120.0940, 30.2185),
         ("云栖方向", 120.0900, 30.2100), ("山坡中段", 120.1005, 30.2150)]

QUERY = """[out:json][timeout:30];
(
  way["landuse"~"orchard|farmland|vineyard|meadow"](%s,%s,%s,%s);
  way["natural"="scrub"](%s,%s,%s,%s);
);
out geom;""" % (BBOX[1], BBOX[0], BBOX[3], BBOX[2], BBOX[1], BBOX[0], BBOX[3], BBOX[2])

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]


def main():
    data = None
    for url in ENDPOINTS:
        for _ in range(3):
            try:
                r = requests.post(url, data={"data": QUERY}, headers=UA, timeout=60)
                if r.status_code == 200:
                    data = r.json(); break
            except Exception:  # noqa: BLE001
                time.sleep(3)
        if data:
            break
    parcels = []
    if data:
        for el in data.get("elements", []):
            geom = el.get("geometry") or []
            ring = [[round(p["lon"], 5), round(p["lat"], 5)] for p in geom if p.get("lon")]
            if len(ring) >= 4:
                parcels.append({"kind": (el.get("tags") or {}).get("landuse") or "scrub", "ring": ring})
    out = {"bbox": BBOX, "n": len(parcels), "parcels": parcels,
           "plots": [{"name": n, "lon": lo, "lat": la} for n, lo, la in PLOTS],
           "note": "OSM 参考边界（可能不完整，仅示意）；地块名为本项目定义的代表地块。"}
    os.makedirs(WEB, exist_ok=True)
    with open(os.path.join(WEB, "terrain_parcels.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"parcels={len(parcels)} plots={len(PLOTS)} -> web/terrain_parcels.json")


if __name__ == "__main__":
    main()