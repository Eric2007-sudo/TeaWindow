"""
农业气象指标引擎：从原始气象数据计算茶树（龙井 43 号）关键指标。
输出 data/processed/daily.csv 与 data/processed/daily.json
指标：有效积温、霜冻/倒春寒、热胁迫、干旱（水分亏缺）、连阴雨、日照。
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
PROC = os.path.join(ROOT, "data", "processed")

BASE_T = 10.0          # 茶树有效积温基温
FROST_TMIN = 2.0       # 霜冻临界最低温
HARD_FROST_TMIN = 0.0


def _load(fn):
    with open(os.path.join(RAW, fn), encoding="utf-8") as f:
        return json.load(f)


def _to_df(obj, source):
    d = obj["daily"]
    df = pd.DataFrame({"date": d["time"]})
    for k, v in d.items():
        if k != "time":
            df[k] = v
    df["date"] = pd.to_datetime(df["date"])
    df["source"] = source
    return df


def compute(df):
    df = df.sort_values("date").reset_index(drop=True)
    num = df.select_dtypes(include=[np.number]).columns
    df[num] = df[num].ffill().bfill()
    df["year"] = df["date"].dt.year
    df["doy"] = df["date"].dt.dayofyear
    df["month"] = df["date"].dt.month

    tmean = df["temperature_2m_mean"]
    # 有效积温（逐日、年内累计）
    df["gdd_day"] = np.maximum(0.0, tmean - BASE_T)
    df["gdd_cum"] = df.groupby("year")["gdd_day"].cumsum()

    # 霜冻 / 倒春寒
    df["frost"] = (df["temperature_2m_min"] <= FROST_TMIN).astype(int)
    df["hard_frost"] = (df["temperature_2m_min"] <= HARD_FROST_TMIN).astype(int)
    warm_before = tmean.rolling(3, min_periods=1).mean().shift(1)
    df["warm_before3"] = warm_before
    df["cold_shock"] = ((df["temperature_2m_min"] <= 4.0) & (warm_before >= 10.0)).astype(int)
    df["cold_shock_sev"] = np.where(
        df["cold_shock"] == 1, np.maximum(0.0, warm_before - df["temperature_2m_min"]), 0.0
    )

    # 热胁迫
    df["heat"] = (df["temperature_2m_max"] >= 35).astype(int)
    df["heat_severe"] = (df["temperature_2m_max"] >= 37).astype(int)
    df["heat_extreme"] = (df["temperature_2m_max"] >= 40).astype(int)

    # 干旱：连旱天数 + 10 日水分亏缺
    dry = (df["precipitation_sum"] < 1.0).astype(int)
    grp = (dry == 0).cumsum()
    df["dry_run"] = dry.groupby(grp).cumsum()
    df["precip_10d"] = df["precipitation_sum"].rolling(10, min_periods=1).sum()
    df["et0_10d"] = df["et0_fao_evapotranspiration"].rolling(10, min_periods=1).sum()
    df["water_deficit_10d"] = df["et0_10d"] - df["precip_10d"]

    # 连阴雨
    wet = (df["precipitation_sum"] >= 0.1).astype(int)
    grp2 = (wet == 0).cumsum()
    df["wet_run"] = wet.groupby(grp2).cumsum()

    # 5 日气温变化（倒春寒/回暖速率）
    df["tmean_5d"] = tmean.rolling(5, min_periods=1).mean()
    df["tmin_5d"] = df["temperature_2m_min"].rolling(5, min_periods=1).min()

    df["is_spring_pick"] = df["month"].isin([3, 4]).astype(int)
    return df


def main():
    os.makedirs(PROC, exist_ok=True)
    arc = _to_df(_load("weather_archive.json"), "archive")
    fc = _to_df(_load("weather_forecast.json"), "forecast")
    df = compute(arc)
    df_fc = compute(pd.concat([arc.tail(30), fc], ignore_index=True))
    df_fc = df_fc[df_fc["source"] == "forecast"]

    cols = [c for c in df.columns if c != "source"]
    df[cols].to_csv(os.path.join(PROC, "daily.csv"), index=False, encoding="utf-8-sig")
    df_fc[cols].to_csv(os.path.join(PROC, "daily_forecast.csv"), index=False, encoding="utf-8-sig")

    # 供前端的小型 JSON（含预报）
    def recs(x):
        out = []
        for _, r in x.iterrows():
            out.append({k: (None if pd.isna(v) else (round(float(v), 2) if isinstance(v, (int, float, np.floating)) else str(v)))
                        for k, v in r.items()})
        return out

    combined = pd.concat([df.tail(400), df_fc], ignore_index=True)
    with open(os.path.join(PROC, "daily.json"), "w", encoding="utf-8") as f:
        json.dump({"history": recs(df), "recent": recs(combined)}, f, ensure_ascii=False)

    # 摘要
    print("历史区间:", df["date"].min().date(), "~", df["date"].max().date(), "n=", len(df))
    for y in range(2015, 2027):
        s = df[df["year"] == y]
        if len(s) == 0:
            continue
        spring = s[s["is_spring_pick"] == 1]
        print(f"{y}: 霜冻日={int(s['frost'].sum()):3d} 倒春寒={int(s['cold_shock'].sum()):2d} "
              f"高温日={int(s['heat'].sum()):3d} 极热={int(s['heat_extreme'].sum()):2d} "
              f"春季maxTmin={spring['temperature_2m_min'].min():5.1f} 春末GDD={spring['gdd_cum'].max():6.0f}")
    print("-> data/processed/daily.csv, daily_forecast.csv, daily.json")


if __name__ == "__main__":
    main()
