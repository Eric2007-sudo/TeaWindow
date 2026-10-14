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


def _get(url, params, retries=5):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60,
                             headers={"User-Agent": "TeaWindow/1.0"})
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 0)) or (8 * (i + 1))
                print(f"  [fetch] 429 限流，等待 {wait}s 重试 ({i+1}/{retries})")
                time.sleep(min(wait, 90))
                last = RuntimeError("429 Too Many Requests")
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
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
    return _get(url, params)


def fetch_forecast(days=16):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT, "longitude": LON,
        "daily": ",".join(DAILY),
        "hourly": "temperature_2m,relative_humidity_2m",
        "forecast_days": days,
        "timezone": TZ,
    }
    return _get(url, params)


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
    if forecast_only and os.path.exists(os.path.join(RAW, "weather_archive.json")):
        print("[archive] 轻量刷新：沿用已有历史（跳过 archive 抓取）")
        arc = {"daily": {"time": []}}
    else:
        print(f"[archive] {start} ~ {end} @ ({LAT},{LON})")
        arc = fetch_archive(start, end)
        with open(os.path.join(RAW, "weather_archive.json"), "w", encoding="utf-8") as f:
            json.dump(arc, f, ensure_ascii=False)
        n = len(arc.get("daily", {}).get("time", []))
        print(f"  历史天数={n}")

    print("[forecast] 未来 16 天")
    fc = fetch_forecast(16)
    fp = os.path.join(RAW, "weather_forecast.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"  预报天数={len(fc.get('daily', {}).get('time', []))}")

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
        "lat": LAT, "lon": LON, "timezone": TZ,
    }
    os.makedirs(PROC, exist_ok=True)
    with open(os.path.join(PROC, "fetch_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("完成 -> data/raw/ + data/processed/fetch_meta.json")


if __name__ == "__main__":
    main()
