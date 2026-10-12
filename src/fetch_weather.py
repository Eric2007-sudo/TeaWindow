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


def _get(url, params, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60,
                             headers={"User-Agent": "TeaWindow/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + i * 2)
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
    if len(sys.argv) > 1:
        start = sys.argv[1]
    if len(sys.argv) > 2:
        end = sys.argv[2]

    print(f"[archive] {start} ~ {end} @ ({LAT},{LON})")
    arc = fetch_archive(start, end)
    with open(os.path.join(RAW, "weather_archive.json"), "w", encoding="utf-8") as f:
        json.dump(arc, f, ensure_ascii=False)
    n = len(arc.get("daily", {}).get("time", []))
    print(f"  历史天数={n}")

    print("[forecast] 未来 16 天")
    fc = fetch_forecast(16)
    with open(os.path.join(RAW, "weather_forecast.json"), "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"  预报天数={len(fc.get('daily', {}).get('time', []))}")
    print("完成 -> data/raw/")


if __name__ == "__main__":
    main()
