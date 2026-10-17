"""
地块级地形风险图（离线生成，公开免密钥 DEM）。
- 数据：AWS Terrain Tiles (Terrarium) 高程瓦片 → 拼接梅家坞 AOI 高程网格。
- 计算：坡度/坡向、山体阴影；地块级"霜冻易感""高温/旱易感"（DEM + 海拔/坡向/坡度 代理）。
- 输出：web/terrain_hillshade.png、web/terrain_frost.png、web/terrain_heat.png、web/terrain_grid.json
用法：python src/terrain_map.py [--z 15]
"""
import argparse
import io
import json
import math
import os
import time

import numpy as np
import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
PROC = os.path.join(ROOT, "data", "processed")

# 梅家坞茶园 AOI（略收紧，突出茶园带）
BBOX = (120.089, 30.207, 120.104, 30.222)   # lon0,lat0,lon1,lat1
UA = {"User-Agent": "TeaWindow/1.0 (climate research; contact: 2302372846@qq.com)"}
TILE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lon2x(lon, z):
    return int((lon + 180.0) / 360.0 * (2 ** z))


def lat2y(lat, z):
    r = math.radians(lat)
    return int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * (2 ** z))


def x2lon(x, z):
    return x / (2 ** z) * 360.0 - 180.0


def y2lat(y, z):
    n = math.pi - 2.0 * math.pi * y / (2 ** z)
    return math.degrees(math.atan(math.sinh(n)))


def fetch_tile(z, x, y):
    for _ in range(3):
        try:
            r = requests.get(TILE.format(z=z, x=x, y=y), headers=UA, timeout=60)
            if r.status_code == 200:
                a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(float)
                return (a[:, :, 0] * 256.0 + a[:, :, 1] + a[:, :, 2] / 256.0) - 32768.0
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def hillshade(elev, res_m, az=315.0, alt=45.0):
    gy, gx = np.gradient(elev, res_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(gy, -gx)
    azr, altr = math.radians(az), math.radians(alt)
    sh = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.clip(sh, 0, 1), np.degrees(slope), (np.degrees(aspect) + 360) % 360


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--z", type=int, default=15)
    a = ap.parse_args()
    z = a.z
    x0, x1 = lon2x(BBOX[0], z), lon2x(BBOX[2], z)
    y0, y1 = lat2y(BBOX[3], z), lat2y(BBOX[1], z)
    print(f"z={z} tiles x{x0}-{x1} y{y0}-{y1} -> {(x1-x0+1)*(y1-y0+1)} tiles")
    mosaics = []
    for y in range(y0, y1 + 1):
        row = []
        for x in range(x0, x1 + 1):
            t = fetch_tile(z, x, y)
            row.append(t if t is not None else np.full((256, 256), np.nan))
        mosaics.append(np.hstack(row))
    elev = np.vstack(mosaics)
    # 缺测填补
    if np.isnan(elev).any():
        elev = np.where(np.isnan(elev), np.nanmean(elev), elev)

    # 逐像素经纬度 → 裁剪到 AOI
    H, W = elev.shape
    lons = np.array([x2lon(x0 + (i + 0.5) / 256.0, z) for i in range(W)])
    lats = np.array([y2lat(y0 + (j + 0.5) / 256.0, z) for j in range(H)])
    ci = np.where((lons >= BBOX[0]) & (lons <= BBOX[2]))[0]
    cj = np.where((lats >= BBOX[1]) & (lats <= BBOX[3]))[0]
    elev = elev[cj[0]:cj[-1] + 1, ci[0]:ci[-1] + 1]
    lons, lats = lons[ci[0]:ci[-1] + 1], lats[cj[0]:cj[-1] + 1]
    H, W = elev.shape
    res_m = 40075016.686 * math.cos(math.radians(30.215)) / (2 ** z) / 256.0
    if np.isnan(elev).any():                                  # 个别瓦片缺失：用整体均值填补
        elev = np.where(np.isnan(elev), float(np.nanmean(elev)), elev)
    print(f"AOI grid {H}x{W}, 分辨率≈{res_m:.1f} m/px, 高程 {elev.min():.0f}~{elev.max():.0f} m")

    sh, slope, aspect = hillshade(elev, res_m)
    e_norm = (elev - elev.min()) / (elev.max() - elev.min() + 1e-9)
    north = (np.cos(np.deg2rad(aspect - 0)) + 1) / 2      # 1=正北
    south = (np.cos(np.deg2rad(aspect - 180)) + 1) / 2    # 1=正南
    gentle = 1 - np.clip(slope / 30.0, 0, 1)
    # 海拔越高越冷、低洼积冷 → 霜冻：低海拔+北向+缓坡
    frost = np.clip(0.45 * (1 - e_norm) + 0.35 * north + 0.20 * gentle, 0, 1)
    # 高温/旱：低海拔+南西向+缓坡（日照强）
    heat = np.clip(0.45 * (1 - e_norm) + 0.35 * south + 0.20 * gentle, 0, 1)

    # 山体阴影底图：多方向光照 + 对比拉伸，地形更清楚
    sh, slope, aspect = hillshade(elev, res_m, az=315.0)
    sh2, _, _ = hillshade(elev, res_m, az=135.0)
    sh = 0.6 * sh + 0.4 * sh2
    lo, hi = np.percentile(sh, 2), np.percentile(sh, 98)
    sh = np.clip((sh - lo) / (hi - lo + 1e-9), 0, 1)
    sh = np.power(sh, 0.85)                                  # 提亮暗部、增强层次
    # 等高线（每 20 m 一条，细、淡）
    band = (np.floor(elev / 20.0).astype(int) % 2 == 0)
    band2 = (np.floor(elev / 100.0).astype(int) % 2 == 0)
    base = (0.16 + 0.84 * sh) * np.where(band, 0.94, 1.0) * np.where(band2, 0.96, 1.0)
    hs = np.dstack([base * 0.92, base * 0.97, base]).clip(0, 1)
    img = Image.fromarray((hs * 255).astype(np.uint8))
    try:                                                     # 轻微锐化，边缘更清晰
        from PIL import ImageFilter
        img = img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=120, threshold=2))
    except Exception:  # noqa: BLE001
        pass
    # 比例尺 + 指北针
    from PIL import ImageDraw
    dr = ImageDraw.Draw(img)
    Wpx, Hpx = img.size
    bar_m = 200.0
    bar_px = int(bar_m / res_m)
    x0, y0 = 18, Hpx - 26
    dr.rectangle([x0 - 6, y0 - 16, x0 + bar_px + 8, y0 + 6], fill=(11, 18, 25))
    dr.line([x0, y0, x0 + bar_px, y0], fill=(255, 255, 255), width=3)
    dr.text((x0, y0 - 14), "200 m", fill=(255, 255, 255))
    dr.polygon([(Wpx - 30, 34), (Wpx - 38, 60), (Wpx - 22, 60)], fill=(255, 255, 255))
    dr.text((Wpx - 40, 62), "N", fill=(255, 255, 255))
    img.save(os.path.join(WEB, "terrain_hillshade.png"))

    def overlay(v):
        # 绿(低)→黄(中)→红(高)，叠加更透（保留地形细节）
        r = np.clip((v - 0.5) * 2.0, 0, 1)
        g = np.clip(1.0 - np.abs(v - 0.5) * 2.0, 0, 1)
        b = np.clip((0.5 - v) * 2.0, 0, 1)
        img2 = np.dstack([hs * (1 - 0.48) + 0.48 * np.dstack([r, g, b])]).clip(0, 1)
        return (img2 * 255).astype(np.uint8)

    Image.fromarray(overlay(frost)).save(os.path.join(WEB, "terrain_frost.png"))
    Image.fromarray(overlay(heat)).save(os.path.join(WEB, "terrain_heat.png"))

    # ---- 逐格点风险下推：站点预报 → 每格点（海拔递减率 + 冷池/坡向修正）----
    ref = float(np.median(elev))
    dtmin = -0.0065 * (elev - ref) - 1.5 * (1 - e_norm)          # 高海拔更冷 + 低洼积冷
    dtmax = -0.0065 * (elev - ref) + 1.2 * south                 # 高海拔更凉 + 南向更晒
    site = {}
    try:
        _d = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
        _fc = [x for x in _d.get("days", []) if x.get("source") == "forecast"]
        if _fc:
            day = max(_fc, key=lambda x: (x.get("risk_R") or 0))
            site = {"date": day.get("date"), "tmin": day.get("tmin"), "tmax": day.get("tmax"),
                    "risk_R": day.get("risk_R"), "risk_level": day.get("risk_level"),
                    "season": (_d.get("meta", {}) or {}).get("season", "off")}
    except Exception:  # noqa: BLE001
        pass
    if site.get("tmin") is not None:
        tmin_c = float(site["tmin"]) + dtmin
        tmax_c = float(site["tmax"] or 30) + dtmax
        frost_s = np.clip((2.0 - tmin_c) / 4.0, 0, 1)             # Tmin≤2℃ 进入霜冻
        heat_s = np.clip((tmax_c - 33.0) / 5.0, 0, 1)             # Tmax≥33℃ 进入高温
        drought_s = np.clip(0.6 * (1 - e_norm) + 0.4 * south, 0, 1) * 0.6
        R_cell = np.clip(np.maximum.reduce([frost_s, heat_s, drought_s]), 0, 1)
        Image.fromarray(overlay(R_cell)).save(os.path.join(WEB, "terrain_risk.png"))
    else:
        R_cell = None

    # 下采样网格（供绘制/悬停查询）：按真实行列输出，保证 JS 的 nx*ny 与 cells 一一对应
    step = max(1, H // 44)
    rows = []
    for j in range(0, H - step + 1, step):
        row = []
        for i in range(0, W - step + 1, step):
            v_f = float(frost[j:j + step, i:i + step].mean())
            v_h = float(heat[j:j + step, i:i + step].mean())
            row.append({"lon": round(float(lons[i + step // 2]), 5),
                        "lat": round(float(lats[j + step // 2]), 5),
                        "elev": int(round(float(elev[j:j + step, i:i + step].mean()))),
                        "slope": round(float(slope[j:j + step, i:i + step].mean()), 1),
                        "aspect": int(round(float(aspect[j:j + step, i:i + step].mean()))),
                        "frost": round(v_f, 2), "heat": round(v_h, 2),
                        "dtmin": round(float(dtmin[j:j + step, i:i + step].mean()), 2),
                        "dtmax": round(float(dtmax[j:j + step, i:i + step].mean()), 2),
                        "drought": round(float(np.clip(0.6 * (1 - e_norm) + 0.4 * south, 0, 1)[j:j + step, i:i + step].mean()), 2),
                        "R": (round(float(R_cell[j:j + step, i:i + step].mean()), 2) if R_cell is not None else None),
                        "tmin_ds": (round(float((float(site.get("tmin")) + dtmin)[j:j + step, i:i + step].mean()), 1) if site.get("tmin") is not None else None)})
        rows.append(row)
    nx = len(rows[0]) if rows else 0
    ny = len(rows)
    g = {"bbox": BBOX, "z": z, "res_m": round(res_m, 1), "step": step, "nx": nx, "ny": ny,
         "cells": [c for r in rows for c in r]}

    def cls(v):
        return "极高" if v >= 0.75 else ("高" if v >= 0.6 else ("中" if v >= 0.4 else "低"))

    for c in g["cells"]:
        c["frost_risk"] = cls(c["frost"])
        c["heat_risk"] = cls(c["heat"])
        if c.get("R") is not None:
            c["risk"] = cls(c["R"])
    top = sorted(g["cells"], key=lambda c: -c["frost"])[:8]
    g["top_frost"] = [{"lon": c["lon"], "lat": c["lat"], "elev": c["elev"], "frost_risk": c["frost_risk"], "frost": c["frost"]} for c in top]
    g["site"] = site
    g["date"] = site.get("date")
    g["top_risk"] = [{"lon": c["lon"], "lat": c["lat"], "elev": c["elev"], "R": c.get("R"), "risk": c.get("risk")}
                     for c in sorted(g["cells"], key=lambda c: -(c.get("R") or 0))[:8]]
    g["method"] = "AWS Terrain Tiles(Terrarium DEM) + 有限差分坡度/坡向；霜冻易感=低海拔+北向+缓坡；高温/旱=低海拔+南向+缓坡；为相对差异，非地块实勘。"
    with open(os.path.join(WEB, "terrain_grid.json"), "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False)
    os.makedirs(PROC, exist_ok=True)
    with open(os.path.join(PROC, "terrain_map.json"), "w", encoding="utf-8") as f:
        json.dump({"bbox": BBOX, "res_m": round(res_m, 1), "n_cells": len(g["cells"]),
                   "elev_min": float(elev.min()), "elev_max": float(elev.max()),
                   "top_frost": g["top_frost"], "method": g["method"]}, f, ensure_ascii=False, indent=2)
    print("输出: web/terrain_hillshade.png, terrain_frost.png, terrain_heat.png, terrain_grid.json")


if __name__ == "__main__":
    main()