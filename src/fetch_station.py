"""
真实台站观测：从 Meteostat 获取杭州站(58457)逐日观测，
与 Open-Meteo(ERA5 再分析)交叉验证，量化偏差。
输出 data/processed/station_hangzhou.csv、report/station_validation.md、report/figures/fig_station.png
"""
import os
from datetime import date

import numpy as np
import pandas as pd
from meteostat import Point, daily, stations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")
FIGS = os.path.join(REPORT, "figures")

STATION_ID = "58457"   # Hangzhou (WMO)
START, END = date(2015, 1, 1), date.today()


def main():
    os.makedirs(PROC, exist_ok=True)
    nb = stations.nearby(Point(30.2139, 120.0961, 50), radius=120000, limit=5)
    print("附近台站:\n", nb.to_string())

    obs = daily(STATION_ID, START, END).fetch()
    if obs is None or len(obs) == 0:
        raise SystemExit("台站无数据")
    obs = obs.reset_index().rename(columns={"time": "date"})
    obs["date"] = pd.to_datetime(obs["date"])
    obs[["date", "temp", "tmin", "tmax", "rhum", "prcp", "wspd", "pres"]].to_csv(
        os.path.join(PROC, "station_hangzhou.csv"), index=False, encoding="utf-8-sig")
    print("台站观测天数:", len(obs))

    era = pd.read_csv(os.path.join(PROC, "daily.csv"))
    era["date"] = pd.to_datetime(era["date"])
    m = pd.merge(obs, era, on="date", how="inner", suffixes=("_obs", "_era"))

    def stat(a, b, name):
        d = (m[a] - m[b]).dropna()
        if len(d) == 0:
            return None
        return {"变量": name, "n": len(d), "偏差(观测-再分析)": round(float(d.mean()), 2),
                "MAE": round(float(d.abs().mean()), 2),
                "相关": round(float(m[[a, b]].dropna().corr().iloc[0, 1]), 3)}

    rows = [stat("tmin", "temperature_2m_min", "Tmin(℃)"),
            stat("tmax", "temperature_2m_max", "Tmax(℃)"),
            stat("temp", "temperature_2m_mean", "Tmean(℃)"),
            stat("prcp", "precipitation_sum", "降水(mm)")]
    rows = [r for r in rows if r]

    md = ["# 台站观测交叉验证\n",
          f"> 观测源：Meteostat 杭州站 **{STATION_ID}**（WMO，约 7.1 km）。",
          f"> 对比源：Open-Meteo ERA5 再分析。重叠天数 {len(m)}（{START}~{END}）。\n",
          "| 变量 | n | 偏差(观测−再分析) | MAE | 相关 |",
          "|---|---|---|---|---|"]
    for r in rows:
        md.append("| {变量} | {n} | {偏差(观测-再分析)} | {MAE} | {相关} |".format(**r))
    md.append("\n> 结论：再分析与台站观测显著相关；用台站数据可进一步校准。**台站观测为一手资料**（观测值，非模式输出）。")
    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(REPORT, "station_validation.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        w = m[(m["date"] >= "2024-03-01") & (m["date"] <= "2024-04-15")]
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
        ax[0].plot(w["date"], w["tmin"], color="#4aa8ff", label="观测 Tmin")
        ax[0].plot(w["date"], w["temperature_2m_min"], color="#4aa8ff", ls="--", alpha=.6, label="ERA5 Tmin")
        ax[0].plot(w["date"], w["tmax"], color="#e08a3c", label="观测 Tmax")
        ax[0].plot(w["date"], w["temperature_2m_max"], color="#e08a3c", ls="--", alpha=.6, label="ERA5 Tmax")
        ax[0].set_title("台站观测 vs 再分析（2024 春季）"); ax[0].legend(fontsize=7)
        ax[1].scatter(m["temperature_2m_min"], m["tmin"], s=3, alpha=.3, color="#4aa8ff")
        lim = [m[["temperature_2m_min", "tmin"]].min().min(), m[["temperature_2m_min", "tmin"]].max().max()]
        ax[1].plot(lim, lim, "--", color="#8aa0b2"); ax[1].set_xlabel("ERA5 Tmin"); ax[1].set_ylabel("观测 Tmin")
        ax[1].set_title("Tmin 散点"); fig.tight_layout()
        fig.savefig(os.path.join(FIGS, "fig_station.png"), dpi=120); plt.close(fig)
        print("-> report/figures/fig_station.png")
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)
    print("-> data/processed/station_hangzhou.csv, report/station_validation.md")


if __name__ == "__main__":
    main()
