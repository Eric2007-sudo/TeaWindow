"""
真实 Sentinel-2 NDVI（数值，非颜色反演）。
- STAC 检索 AOI 内低云 L2A 场景；用 tifffile + HTTP Range 读 COG 概览层窗口；
- 手动 UTM(51N) 坐标换算定位 AOI；计算 NDVI=(NIR-Red)/(NIR+Red) 均值。
输出 data/processed/s2_ndvi.json
依赖：tifffile（纯 python）。网络：需可访问 sentinel-cogs S3（国内可设代理）。
"""
import json
import math
import os
import time
import urllib.request
from datetime import date, datetime, timedelta

import numpy as np
import tifffile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

AOI = (120.085, 30.204, 120.106, 30.226)  # lon0,lat0,lon1,lat1
UA = {"User-Agent": "TeaWindow/1.0"}
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:10090"
if PROXY:
    urllib.request.install_opener(urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})))


def http(req, tries=6):
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=90).read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + 2 * i)
    raise last


class RangeFile:
    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.size = int(urllib.request.urlopen(
            urllib.request.Request(url, method="HEAD", headers=UA), timeout=60).headers["Content-Length"])

    def read(self, n=-1):
        end = self.size - 1 if (n is None or n < 0) else min(self.size - 1, self.pos + n - 1)
        if self.pos > end:
            return b""
        d = http(urllib.request.Request(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"}))
        self.pos += len(d)
        return d

    def seek(self, p, w=0):
        self.pos = p if w == 0 else (self.pos + p if w == 1 else self.size + p)
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def close(self):
        pass


def latlon_to_utm(lat, lon, zone):
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    lon0 = math.radians(zone * 6 - 183)
    lat, lon = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    T, C = math.tan(lat) ** 2, ep2 * math.cos(lat) ** 2
    A = (lon - lon0) * math.cos(lat)
    M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * lat
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * lat)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * lat)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * lat))
    E = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000
    Nn = k0 * (M + N * math.tan(lat) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
              + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720))
    return E, Nn


def stac_scenes(start, end):
    body = {"bbox": list(AOI), "datetime": f"{start}T00:00:00Z/{end}T00:00:00Z",
            "collections": ["sentinel-2-l2a"], "limit": 80,
            "query": {"eo:cloud_cover": {"lt": 25}}}
    req = urllib.request.Request("https://earth-search.aws.element84.com/v1/search",
                                 data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json"})
    return json.loads(http(req))["features"]


def pick_level(tf, target=700):
    levels = tf.series[0].levels
    best = len(levels) - 1
    for i, lv in enumerate(levels):
        if lv.shape[0] <= target:
            best = i
            break
    return best


def _transform(tf):
    """取全分辨率页的地理变换(像素尺度+左上角)。"""
    base = tf.pages[0]
    sx, sy, _ = base.tags["ModelPixelScaleTag"].value
    tp = base.tags["ModelTiepointTag"].value
    return float(sx), float(sy), float(tp[3]), float(tp[4]), int(base.shape[1])


def ndvi_for_scene(red_href, nir_href):
    tf_r = tifffile.TiffFile(RangeFile(red_href))
    tf_n = tifffile.TiffFile(RangeFile(nir_href))
    sxr0, syr0, X0r, Y0r, w_r0 = _transform(tf_r)
    sxn0, syn0, X0n, Y0n, w_n0 = _transform(tf_n)
    lr, ln = pick_level(tf_r), pick_level(tf_n)
    ar = tf_r.series[0].levels[lr].asarray().astype("float32")
    an = tf_n.series[0].levels[ln].asarray().astype("float32")
    # 概览层像素尺度 = 全分辨率尺度 × 缩放因子
    sxr, syr = sxr0 * (w_r0 / ar.shape[1]), syr0 * (w_r0 / ar.shape[1])
    sxn, syn = sxn0 * (w_n0 / an.shape[1]), syn0 * (w_n0 / an.shape[1])
    zone = 51
    E0, N1 = latlon_to_utm(AOI[1], AOI[0], zone)
    E1, N0 = latlon_to_utm(AOI[3], AOI[2], zone)

    def win(sx, sy, X0, Y0, shape):
        x0 = int((min(E0, E1) - X0) / sx); x1 = int((max(E0, E1) - X0) / sx) + 1
        y0 = int((Y0 - max(N0, N1)) / sy); y1 = int((Y0 - min(N0, N1)) / sy) + 1
        x0, x1 = max(0, x0), min(shape[1], x1)
        y0, y1 = max(0, y0), min(shape[0], y1)
        return x0, x1, y0, y1

    x0r, x1r, y0r, y1r = win(sxr, syr, X0r, Y0r, ar.shape)
    if x1r <= x0r or y1r <= y0r:
        return None
    x0n, x1n, y0n, y1n = win(sxn, syn, X0n, Y0n, an.shape)
    r = np.nanmean(ar[y0r:y1r, x0r:x1r])
    n = np.nanmean(an[y0n:y1n, x0n:x1n])
    if not np.isfinite(r) or not np.isfinite(n) or (r + n) == 0:
        return None
    return float((n - r) / (n + r))


def main():
    os.makedirs(PROC, exist_ok=True)
    end = date.today()
    start = end - timedelta(days=400)
    feats = stac_scenes(start.isoformat(), end.isoformat())
    print("候选场景:", len(feats))
    # 按日期分组，取每日最低云量场景
    per_day = {}
    for ft in feats:
        d = ft["properties"]["datetime"][:10]
        cc = ft["properties"].get("eo:cloud_cover", 100)
        if d not in per_day or cc < per_day[d][0]:
            per_day[d] = (cc, ft)
    series = []
    days = sorted(per_day)
    if len(days) > 6:  # 均匀采样约 6 期，控制耗时
        idx = np.linspace(0, len(days) - 1, 6).round().astype(int)
        days = [days[i] for i in dict.fromkeys(idx)]
    outp = os.path.join(PROC, "s2_ndvi.json")

    def save():
        with open(outp, "w", encoding="utf-8") as f:
            json.dump({"source": "Copernicus Sentinel-2 L2A（10m，读取约 160m 概览层，数值 NDVI）",
                       "aoi": {"lon0": AOI[0], "lat0": AOI[1], "lon1": AOI[2], "lat1": AOI[3]},
                       "series": series,
                       "note": "数值 NDVI，非颜色反演；云量<25 的最佳场景；逐景即时写盘。"},
                      f, ensure_ascii=False, indent=2)

    print("采样日期:", days, flush=True)
    for d in days:
        cc, ft = per_day[d]
        try:
            print(f"  处理 {d} ...", flush=True)
            v = ndvi_for_scene(ft["assets"]["red"]["href"], ft["assets"]["nir"]["href"])
            if v is not None:
                series.append({"date": d, "ndvi": round(v, 3), "cloud": round(cc, 1), "tile": ft["id"][:20]})
                print(f"  {d} ndvi={v:.3f} cloud={cc:.0f} {ft['id'][:22]}", flush=True)
                save()
        except Exception as e:  # noqa: BLE001
            print(f"  {d} ERR {str(e)[:70]}", flush=True)
    save()
    print(f"有效点数={len(series)} -> data/processed/s2_ndvi.json")


if __name__ == "__main__":
    main()
