"""
接入外部一手数据（台站/自建传感器 CSV）并计算农业气象指标。
用法：
  python src\\sensor_ingest.py 输入.csv [输出.csv]
支持列名（大小写/中英皆可）：
  date/time/日期 ; tmin ; tmax ; tmean/temp ; prcp/precip/降水 ; rh/rhum/湿度
缺失的其它变量用合理默认值补齐（会打印说明）。
"""
import os
import sys

import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
import indices  # noqa: E402

CANDS = {
    "date": ["date", "time", "日期", "datetime", "Date", "TIME"],
    "tmax": ["tmax", "temperature_2m_max", "最高温", "tmax_c", "TMAX"],
    "tmin": ["tmin", "temperature_2m_min", "最低温", "tmin_c", "TMIN"],
    "tmean": ["tmean", "temp", "temperature_2m_mean", "平均温", "TAVG"],
    "prcp": ["prcp", "precip", "precipitation_sum", "降水", "rain", "PRCP"],
    "rh": ["rhum", "rh", "relative_humidity_2m_mean", "湿度", "humidity"],
}
DEFAULTS = {"relative_humidity_2m_mean": 70.0, "et0_fao_evapotranspiration": 2.5,
            "shortwave_radiation_sum": 15.0, "sunshine_duration": 20000.0,
            "wind_speed_10m_max": 10.0, "soil_moisture_0_to_7cm_mean": 0.30}


def pick(df, kinds):
    for c in kinds:
        for col in df.columns:
            if str(col).strip().lower() == c.lower() or str(col).strip() == c:
                return col
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("data", "processed", "external_indices.csv")
    raw = pd.read_csv(inp, encoding="utf-8-sig")
    print("输入列:", list(raw.columns))

    cols = {k: pick(raw, v) for k, v in CANDS.items()}
    if not cols["date"] or not cols["tmax"] or not cols["tmin"]:
        raise SystemExit("至少需要 date + tmax + tmin 三列")
    df = pd.DataFrame()
    df["date"] = pd.to_datetime(raw[cols["date"]])
    df["temperature_2m_max"] = pd.to_numeric(raw[cols["tmax"]], errors="coerce")
    df["temperature_2m_min"] = pd.to_numeric(raw[cols["tmin"]], errors="coerce")
    df["temperature_2m_mean"] = (pd.to_numeric(raw[cols["tmean"]], errors="coerce")
                                 if cols["tmean"] else (df["temperature_2m_max"] + df["temperature_2m_min"]) / 2)
    df["precipitation_sum"] = (pd.to_numeric(raw[cols["prcp"]], errors="coerce").fillna(0.0)
                               if cols["prcp"] else 0.0)
    df["relative_humidity_2m_mean"] = (pd.to_numeric(raw[cols["rh"]], errors="coerce")
                                       if cols["rh"] else np.nan)
    for k, v in DEFAULTS.items():
        if k not in df:
            df[k] = v
    df["relative_humidity_2m_mean"] = df["relative_humidity_2m_mean"].fillna(DEFAULTS["relative_humidity_2m_mean"])
    df = df.dropna(subset=["temperature_2m_max", "temperature_2m_min"]).sort_values("date")

    res = indices.compute(df)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    res.to_csv(out, index=False, encoding="utf-8-sig")

    print("\n== 外部数据指标摘要 ==")
    print("区间:", res["date"].min().date(), "~", res["date"].max().date(), "天数:", len(res))
    for y, g in res.groupby("year"):
        print(f"{y}: 霜冻日={int(g['frost'].sum()):3d} 倒春寒={int(g['cold_shock'].sum()):2d} "
              f"高温日={int(g['heat'].sum()):3d} Tmin最低={g['temperature_2m_min'].min():.1f} "
              f"Tmax最高={g['temperature_2m_max'].max():.1f}")
    print("-> ", out)
    print("提示：可用于与 ERA5/模型结果对照，或替换数据源后重跑 model.py。")


if __name__ == "__main__":
    main()
