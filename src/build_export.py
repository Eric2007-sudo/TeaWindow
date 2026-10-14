"""
汇总导出：生成前端离线数据 web/data.json。
- 对历史与预报统一计算风险(R)、风险等级、采摘适宜度；
- 生成未来 16 天与近 14 天的白话建议；
- 合并遥感(NDVI/S2)、模型指标。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from model import build_features, rubric, GBDT  # noqa: E402
from qa import nlg  # noqa: E402

ROOT = os.path.dirname(SRC)
PROC = os.path.join(ROOT, "data", "processed")
WEB = os.path.join(ROOT, "web")
MODELS = os.path.join(ROOT, "models")


def enrich(df, model=None, train=True):
    X = build_features(df).values.astype(float)
    y, R = rubric(df)
    if train:
        m = GBDT().fit(X, np.asarray(y).astype(float))
    else:
        m = model
    df = df.copy()
    df["risk_prob"] = m.predict_proba(X)
    df["risk_R"] = np.asarray(R)
    df["hazard"] = np.asarray(y).astype(int)
    df["risk_level"] = pd.cut(df["risk_R"], [-0.01, 0.25, 0.5, 0.75, 1.01],
                              labels=["低", "中", "高", "极高"]).astype(str)
    comfort = np.clip(1 - np.abs(df["temperature_2m_mean"] - 18) / 12, 0, 1)
    rain_pen = np.clip(df["precipitation_sum"] / 10, 0, 1)
    sun = np.clip(df["sunshine_duration"] / 3600 / 8, 0, 1)
    wind_pen = np.clip((df["wind_speed_10m_max"] - 20) / 30, 0, 1)
    df["suitability"] = (100 * np.clip(0.45 * comfort + 0.2 * sun - 0.35 * rain_pen
                                       - 0.2 * wind_pen - 0.9 * np.asarray(R), 0, 1)).round(0)
    return df, m


FIELDS = ["date", "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
          "precipitation_sum", "relative_humidity_2m_mean", "et0_fao_evapotranspiration",
          "sunshine_duration", "wind_speed_10m_max", "soil_moisture_0_to_7cm_mean",
          "gdd_cum", "dry_run", "wet_run", "water_deficit_10d",
          "risk_prob", "risk_R", "risk_level", "hazard", "suitability",
          "frost", "cold_shock", "heat", "heat_severe"]
RENAME = {"temperature_2m_max": "tmax", "temperature_2m_min": "tmin",
          "temperature_2m_mean": "tmean", "precipitation_sum": "precip",
          "relative_humidity_2m_mean": "rh", "et0_fao_evapotranspiration": "et0",
          "sunshine_duration": "sun_s", "wind_speed_10m_max": "wind",
          "soil_moisture_0_to_7cm_mean": "soil", "water_deficit_10d": "deficit"}


def recs(df, source):
    out = []
    for _, r in df.iterrows():
        d = {"source": source}
        for k in FIELDS:
            v = r[k]
            if isinstance(v, (np.floating, float)):
                d[RENAME.get(k, k)] = None if pd.isna(v) else round(float(v), 3)
            elif isinstance(v, (np.integer,)):
                d[RENAME.get(k, k)] = int(v)
            else:
                d[RENAME.get(k, k)] = str(v)[:10] if k == "date" else v
        out.append(d)
    return out


def main():
    hist = pd.read_csv(os.path.join(PROC, "daily.csv"))
    fc = pd.read_csv(os.path.join(PROC, "daily_forecast.csv"))
    for d in (hist, fc):
        d["date"] = pd.to_datetime(d["date"])
    hist["date"] = hist["date"].dt.strftime("%Y-%m-%d")
    fc["date"] = fc["date"].dt.strftime("%Y-%m-%d")
    hist["date"] = pd.to_datetime(hist["date"])
    fc["date"] = pd.to_datetime(fc["date"])

    hist_e, model = enrich(hist, train=True)
    fc_e, _ = enrich(fc, model=model, train=False)

    recent = hist_e.tail(180)

    # 采摘窗口：仅春采季(3–4月)生成；非春采期停用（统一业务层季节策略，Asia/Shanghai）
    import season as _season
    _today = _season.today()
    season_name = _season.policy(_today)["season"]
    season_off = (season_name == "off")
    if season_off:
        window = []
    else:
        fc_future = fc_e[fc_e["date"].dt.date >= _today]
        win = fc_future.sort_values("suitability", ascending=False).head(5)
        window = [{"date": str(r["date"])[:10], "suitability": float(r["suitability"]),
                   "risk_level": str(r["risk_level"])} for _, r in win.iterrows()]

    with open(os.path.join(PROC, "ndvi.json"), encoding="utf-8") as f:
        ndvi = json.load(f)
    with open(os.path.join(MODELS, "metrics.json"), encoding="utf-8") as f:
        metrics = json.load(f)
    terrain = calib = None
    tp = os.path.join(PROC, "terrain.json")
    cp = os.path.join(MODELS, "calibration.json")
    if os.path.exists(tp):
        with open(tp, encoding="utf-8") as f:
            terrain = json.load(f)
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            calib = json.load(f)
    ens = None
    ep = os.path.join(PROC, "ensemble.json")
    if os.path.exists(ep):
        with open(ep, encoding="utf-8") as f:
            ens = json.load(f)
    ensmap = {s["date"]: s for s in ens["series"]} if ens else {}
    s2 = None
    sp = os.path.join(PROC, "s2_ndvi.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            s2 = json.load(f)

    days = []
    for r in recs(recent, "history") + recs(fc_e, "forecast"):
        dt = r["date"]
        r["advice"] = nlg.day_advice(r, season_off)
        r["advice_source"] = "teawindow-own"
        if r["source"] == "forecast" and dt in ensmap:
            s = ensmap[dt]
            r["p_frost"] = s["p_frost"]
            r["p_heat"] = s["p_heat"]
            r["tmin_lo"] = s["tmin_p10"]; r["tmin_hi"] = s["tmin_p90"]
            r["tmax_lo"] = s["tmax_p10"]; r["tmax_hi"] = s["tmax_p90"]
        days.append(r)

    data = {
        "meta": {
            "site": "梅家坞（西湖龙井核心产区）", "lat": 30.2139, "lon": 120.0961,
            "updated": _season.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fetched_at": _season.now().strftime("%Y-%m-%d %H:%M:%S"),
            "season": _season.policy()["season"],
            "sources": [
                "Open-Meteo ERA5 历史 + 预报（气象）",
                "NASA GIBS MODIS_Terra_NDVI_8Day（遥感，颜色近似反演）",
                "Element84 Earth Search Sentinel-2 L2A（场景清单）",
            ],
            "disclaimer": "风险指标与建议为决策辅助，存在不确定性，不替代田间实勘与农技指导。",
        },
        "metrics": metrics,
        "ndvi": ndvi,
        "s2_ndvi": s2,
        "terrain": terrain,
        "calibration": calib,
        "ensemble": ens,
        "pick_window": window,
        "days": days,
    }
    os.makedirs(WEB, exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(WEB, "data.json"), "w", encoding="utf-8") as f:
        f.write(blob)
    with open(os.path.join(WEB, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.TW_DATA = " + blob + ";\n")
    print(f"days={len(days)} (hist {len(recent)} + fc {len(fc_e)}), advice=rules(自研)")
    print("pick_window:", window)
    print("-> web/data.json")


if __name__ == "__main__":
    main()
