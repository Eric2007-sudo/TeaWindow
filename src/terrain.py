"""
地块级地形：用 Open-Meteo elevation 采样网格，计算海拔/坡度/坡向，
并给出"地形霜冻易感系数"（低洼、北向、坡缓更易积冷霜冻）。
数据源公开、免密钥。输出 data/processed/terrain.json
"""
import json
import os
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

# 梅家坞外接矩形（lon0,lat0,lon1,lat1）
BBOX = (120.085, 30.204, 120.106, 30.226)
NX, NY = 7, 7  # 采样网格
UA = {"User-Agent": "TeaWindow/1.0"}

# 代表地块（名称, 经度, 纬度）
PLOTS = [
    ("梅家坞村口", 120.0935, 30.2115),
    ("梅坞溪谷", 120.0961, 30.2139),
    ("北坡茶园", 120.0985, 30.2160),
    ("山坡中段", 120.1005, 30.2150),
    ("高处茶园", 120.0940, 30.2185),
    ("云栖方向", 120.0900, 30.2100),
]


def fetch_elevations(points):
    """points: list[(lat,lon)] -> list[float]"""
    out = []
    for i in range(0, len(points), 90):
        chunk = points[i:i + 90]
        loc = "|".join(f"{la},{lo}" for la, lo in chunk)
        url = f"https://api.open-meteo.com/v1/elevation?latitude=" + \
              ",".join(str(la) for la, _ in chunk) + "&longitude=" + \
              ",".join(str(lo) for _, lo in chunk)
        for attempt in range(3):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
                out.extend(json.loads(raw)["elevation"])
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        else:
            out.extend([np.nan] * len(chunk))
    return out


def main():
    os.makedirs(PROC, exist_ok=True)
    lons = np.linspace(BBOX[0], BBOX[2], NX)
    lats = np.linspace(BBOX[1], BBOX[3], NY)
    grid = [(la, lo) for la in lats for lo in lons]
    elev = np.array(fetch_elevations(grid), dtype=float).reshape(NY, NX)
    # 若个别缺测，用邻域均值填补
    if np.isnan(elev).any():
        elev = np.where(np.isnan(elev), np.nanmean(elev), elev)

    # 坡度/坡向（近似：按格网间距的有限差分）
    dlat = (BBOX[3] - BBOX[1]) / (NY - 1)
    dlon = (BBOX[2] - BBOX[0]) / (NX - 1)
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * np.cos(np.deg2rad((BBOX[1] + BBOX[3]) / 2))
    gy, gx = np.gradient(elev, dlat * m_per_deg_lat, dlon * m_per_deg_lon)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = (np.degrees(np.arctan2(gy, -gx)) + 360) % 360  # 0=北

    # 地形霜冻易感系数：低海拔+缓坡+北/东向 更易霜冻
    e_norm = (elev - np.nanmin(elev)) / (np.nanmax(elev) - np.nanmin(elev) + 1e-9)
    northliness = np.clip(np.cos(np.deg2rad(aspect - 0)), -1, 1)  # 1=正北
    gentle = 1 - np.clip(slope / 30.0, 0, 1)                      # 越平越易积冷
    frost_factor = np.clip(0.5 * (1 - e_norm) + 0.3 * ((northliness + 1) / 2) + 0.2 * gentle, 0, 1)

    def nearest(lat, lon):
        j = int(np.clip(round((lat - BBOX[1]) / (BBOX[3] - BBOX[1]) * (NY - 1)), 0, NY - 1))
        i = int(np.clip(round((lon - BBOX[0]) / (BBOX[2] - BBOX[0]) * (NX - 1)), 0, NX - 1))
        return j, i

    plots = []
    for name, lo, la in PLOTS:
        j, i = nearest(la, lo)
        e = float(elev[j, i]); s = float(slope[j, i]); a = float(aspect[j, i]); ff = float(frost_factor[j, i])
        plots.append({"name": name, "lon": lo, "lat": la, "elev_m": round(e, 1),
                      "slope_deg": round(s, 1), "aspect_deg": round(a, 1),
                      "frost_factor": round(ff, 2),
                      "frost_risk": "高" if ff >= 0.6 else ("中" if ff >= 0.4 else "低")})

    out = {
        "bbox": BBOX, "grid": {"nx": NX, "ny": NY,
                               "lons": [round(x, 5) for x in lons], "lats": [round(x, 5) for x in lats],
                               "elev": [[round(float(v), 1) for v in row] for row in elev]},
        "plots": plots,
        "method": "Open-Meteo elevation 网格采样 + 有限差分坡度/坡向；霜冻易感=低海拔+北向+缓坡 加权",
        "disclaimer": "DEM 分辨率约 90m，用于相对差异，不代表地块实勘结果。",
    }
    with open(os.path.join(PROC, "terrain.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("海拔范围: %.0f~%.0f m" % (np.nanmin(elev), np.nanmax(elev)))
    for p in plots:
        print(f"  {p['name']}: {p['elev_m']}m 坡{p['slope_deg']}° 向{p['aspect_deg']}° 霜冻易感={p['frost_risk']}({p['frost_factor']})")
    print("-> data/processed/terrain.json")


if __name__ == "__main__":
    main()
