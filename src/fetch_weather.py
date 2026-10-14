"""
数据管线：抓取梅家坞（西湖龙井核心产区）历史与预报气象数据。
数据源：Open-Meteo (ERA5 历史 + 预报)，公开、免费、免密钥。
坐标：梅家坞村约 30.2139N, 120.0961E。
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

LAT = 30.2139
LON = 120.0961
TZ = "Asia/Shanghai"
OM_KEY = os.environ.get("OPEN_METEO_API_KEY", "")


def _om(url, params):
    """Open-Meteo：配置 API key 时改用 customer 端点并附带 apikey（避免共享出口限流）。"""
    p = dict(params)
    if OM_KEY:
        url = url.replace("archive-api.open-meteo.com", "customer-archive-api.open-meteo.com") \
                 .replace("ensemble-api.open-meteo.com", "customer-ensemble-api.open-meteo.com") \
                 .replace("historical-forecast-api.open-meteo.com", "customer-historical-forecast-api.open-meteo.com") \
                 .replace("previous-runs-api.open-meteo.com", "customer-previous-runs-api.open-meteo.com") \
                 .replace("https://api.open-meteo.com", "https://customer-api.open-meteo.com")
        p["apikey"] = OM_KEY
    return url, p

DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "relative_humidity_2m_mean",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum",
    "sunshine_duration",
    "wind_speed_10m_max",
    "soil_moisture_0_to_7cm_mean",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
PROC = os.path.join(ROOT, "data", "processed")


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def _now():
    try:
        from zoneinfo import ZoneInfo
        import datetime
        return datetime.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get(url, params, retries=5, fast429=False):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60,
                             headers={"User-Agent": "TeaWindow/1.0"})
            if r.status_code == 429:
                if fast429:
                    raise RuntimeError("429 Too Many Requests")
                wait = int(r.headers.get("Retry-After", 0)) or (8 * (i + 1))
                print(f"  [fetch] 429 限流，等待 {wait}s 重试 ({i+1}/{retries})")
                time.sleep(min(wait, 90))
                last = RuntimeError("429 Too Many Requests")
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            if fast429:
                raise
            time.sleep(2 + i * 3)
    raise RuntimeError(f"请求失败: {last}")


def fetch_archive(start, end):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LAT, "longitude": LON,
        "start_date": start, "end_date": end,
        "daily": ",".join(DAILY),
        "timezone": TZ,
    }
    return _get(*_om(url, params))


def fetch_forecast(days=16):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT, "longitude": LON,
        "daily": ",".join(DAILY),
        "hourly": "temperature_2m,relative_humidity_2m",
        "forecast_days": days,
        "timezone": TZ,
    }
    return _get(*_om(url, params), fast429=True)   # 429 快速失败 → 立即切备用源


def fetch_forecast_metno(days=16):
    """备用源：MET Norway Locationforecast（hourly→daily 聚合，字段名对齐 Open-Meteo）。"""
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    r = requests.get(url, params={"lat": LAT, "lon": LON},
                     headers={"User-Agent": "TeaWindow/1.0 (climate prototype; contact: teawindow)"}, timeout=60)
    r.raise_for_status()
    ts = r.json()["properties"]["timeseries"]
    byday = {}
    for e in ts:
        day = e["time"][:10]
        d = e["data"]["instant"]["details"]
        t = d.get("air_temperature")
        p = (e["data"].get("next_1_hours", {}) or {}).get("details", {}).get("precipitation_amount")
        b = byday.setdefault(day, {"tmin": 1e9, "tmax": -1e9, "precip": 0.0, "rh": []})
        if t is not None:
            b["tmin"] = min(b["tmin"], t); b["tmax"] = max(b["tmax"], t)
        if p:
            b["precip"] += p
        if d.get("relative_humidity") is not None:
            b["rh"].append(d["relative_humidity"])
    days_sorted = sorted(byday)[:days]
    out = {"latitude": LAT, "longitude": LON, "timezone": TZ, "_source": "met.no",
           "daily": {"time": days_sorted, "temperature_2m_max": [], "temperature_2m_min": [],
                     "temperature_2m_mean": [], "precipitation_sum": [], "relative_humidity_2m_mean": []}}
    for day in days_sorted:
        b = byday[day]
        tmin = None if b["tmin"] > 1e8 else round(b["tmin"], 1)
        tmax = None if b["tmax"] < -1e8 else round(b["tmax"], 1)
        out["daily"]["temperature_2m_min"].append(tmin)
        out["daily"]["temperature_2m_max"].append(tmax)
        out["daily"]["temperature_2m_mean"].append(round(((tmin or 0) + (tmax or 0)) / 2, 1))
        out["daily"]["precipitation_sum"].append(round(b["precip"], 1))
        out["daily"]["relative_humidity_2m_mean"].append(round(sum(b["rh"]) / len(b["rh"]), 0) if b["rh"] else None)
    return out


def main():
    os.makedirs(RAW, exist_ok=True)
    end = (date.today() - timedelta(days=2)).isoformat()
    start = "2015-01-01"
    import re as _re
    _isdate = lambda s: bool(_re.fullmatch(r"\d{4}-\d{2}-\d{2}", s or ""))
    if len(sys.argv) > 1 and _isdate(sys.argv[1]):
        start = sys.argv[1]
    if len(sys.argv) > 2 and _isdate(sys.argv[2]):
        end = sys.argv[2]

    forecast_only = os.environ.get("TW_FETCH_FORECAST_ONLY") == "1"
    ap_ = os.path.join(RAW, "weather_archive.json")
    if forecast_only and os.path.exists(ap_):
        print("[archive] 轻量刷新：沿用已有历史（跳过 archive 抓取）")
        arc = {"daily": {"time": []}}
    else:
        try:
            print(f"[archive] {start} ~ {end} @ ({LAT},{LON})")
            arc = fetch_archive(start, end)
            with open(ap_, "w", encoding="utf-8") as f:
                json.dump(arc, f, ensure_ascii=False)
            n = len(arc.get("daily", {}).get("time", []))
            print(f"  历史天数={n}")
        except Exception as e:  # noqa: BLE001
            if os.path.exists(ap_):
                print("[archive] 抓取失败，回退本地缓存:", e)
                arc = json.load(open(ap_, encoding="utf-8"))
            else:
                raise

    print("[forecast] 未来 16 天")
    fp = os.path.join(RAW, "weather_forecast.json")
    src = "open-meteo"
    fc = None
    _force = os.environ.get("FORECAST_SOURCE", "auto")
    if _force == "metno":
        try:
            fc = fetch_forecast_metno(16); src = "met.no"; print("  [forecast] 指定首选 MET Norway")
        except Exception as e:  # noqa: BLE001
            print("  [forecast] MET Norway 失败:", e)
    if fc is None and _force != "metno":
        try:
            fc = fetch_forecast(16)
        except Exception as e:  # noqa: BLE001
            print("  [forecast] Open-Meteo 失败:", e)
    if fc is None:
        try:
            fc = fetch_forecast_metno(16)
            src = "met.no"
            print("  [forecast] 使用备用源 MET Norway")
        except Exception as e2:  # noqa: BLE001
            print("  [forecast] 备用源失败:", e2)
    if fc is None and os.path.exists(fp):
        fc = json.load(open(fp, encoding="utf-8"))
        src = "cached"
        print("  [forecast] 使用本地缓存（回退）")
    if fc is None:
        raise RuntimeError("预报抓取失败且无本地缓存")
    fc["_source"] = src
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"  预报天数={len(fc.get('daily', {}).get('time', []))} 来源={src}")

    # 数据版本元数据：上游 URL/参数/原始 SHA-256/抓取时间（供数据血缘与复现）
    meta = {
        "fetched_at": _now(),
        "forecast_url": "https://api.open-meteo.com/v1/forecast",
        "forecast_params": {"latitude": LAT, "longitude": LON, "forecast_days": 16, "timezone": TZ,
                            "daily": ",".join(DAILY)},
        "archive_url": "https://archive-api.open-meteo.com/v1/archive",
        "archive_params": {"latitude": LAT, "longitude": LON, "start_date": start, "end_date": end, "timezone": TZ},
        "forecast_raw_sha256": _sha256(fp),
        "archive_raw_sha256": _sha256(os.path.join(RAW, "weather_archive.json")),
        "forecast_source": src, "om_api_key": bool(OM_KEY),
        "lat": LAT, "lon": LON, "timezone": TZ,
    }
    os.makedirs(PROC, exist_ok=True)
    with open(os.path.join(PROC, "fetch_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("完成 -> data/raw/ + data/processed/fetch_meta.json")


if __name__ == "__main__":
    main()
