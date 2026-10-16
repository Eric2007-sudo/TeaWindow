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

    # 山体阴影底图
    base = (0.35 + 0.65 * sh)
    hs = np.dstack([base * 0.90, base * 0.95, base]).clip(0, 1)
    Image.fromarray((hs * 255).astype(np.uint8)).save(os.path.join(WEB, "terrain_hillshade.png"))

    def overlay(v):
        # 绿(低)→黄(中)→红(高)
        r = np.clip((v - 0.5) * 2.0, 0, 1)
        g = np.clip(1.0 - np.abs(v - 0.5) * 2.0, 0, 1)
        b = np.clip((0.5 - v) * 2.0, 0, 1)
        img = np.dstack([hs * (1 - 0.55) + 0.55 * np.dstack([r, g, b])]).clip(0, 1)
        return (img * 255).astype(np.uint8)

    Image.fromarray(overlay(frost)).save(os.path.join(WEB, "terrain_frost.png"))
    Image.fromarray(overlay(heat)).save(os.path.join(WEB, "terrain_heat.png"))

    # 下采样网格（供悬停查询）
    step = max(1, H // 44)
    g = {"bbox": BBOX, "z": z, "res_m": round(res_m, 1), "nx": W // step, "ny": H // step,
         "cells": []}
    for j in range(0, H - step, step):
        for i in range(0, W - step, step):
            v_f = float(frost[j:j + step, i:i + step].mean())
            v_h = float(heat[j:j + step, i:i + step].mean())
            g["cells"].append({"lon": round(float(lons[i + step // 2]), 5),
                               "lat": round(float(lats[j + step // 2]), 5),
                               "elev": int(round(float(elev[j:j + step, i:i + step].mean()))),
                               "slope": round(float(slope[j:j + step, i:i + step].mean()), 1),
                               "aspect": int(round(float(aspect[j:j + step, i:i + step].mean()))),
                               "frost": round(v_f, 2), "heat": round(v_h, 2)})

    def cls(v):
        return "极高" if v >= 0.75 else ("高" if v >= 0.6 else ("中" if v >= 0.4 else "低"))

    for c in g["cells"]:
        c["frost_risk"] = cls(c["frost"])
        c["heat_risk"] = cls(c["heat"])
    top = sorted(g["cells"], key=lambda c: -c["frost"])[:8]
    g["top_frost"] = [{"lon": c["lon"], "lat": c["lat"], "elev": c["elev"], "frost_risk": c["frost_risk"], "frost": c["frost"]} for c in top]
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