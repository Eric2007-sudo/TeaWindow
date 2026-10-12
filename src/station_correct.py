"""
台站偏差订正：用杭州站(WMO 58457)逐日观测对 ERA5 做逐月偏差订正。
输出 data/processed/daily_corrected.csv、report/station_correction.md、report/figures/fig_correction.png

说明：订正目标是观测站（城市站，海拔 43m），与梅家坞山谷存在真实微气候差异，
因此订正后结果代表"更接近杭州城市观测"的序列；残留差异反映山谷效应（已在报告中声明）。
"""
import os
import sys

import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
import indices  # noqa: E402

ROOT = os.path.dirname(SRC)
PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")
FIGS = os.path.join(REPORT, "figures")

PAIRS = [("tmin", "temperature_2m_min"), ("tmax", "temperature_2m_max"), ("temp", "temperature_2m_mean")]


def main():
    era = pd.read_csv(os.path.join(PROC, "daily.csv"))
    era["date"] = pd.to_datetime(era["date"])
    obs = pd.read_csv(os.path.join(PROC, "station_hangzhou.csv"))
    obs["date"] = pd.to_datetime(obs["date"])
    m = pd.merge(obs[["date", "tmin", "tmax", "temp"]], era, on="date", how="inner")
    m["month"] = m["date"].dt.month

    # 逐月偏差 (观测 − ERA5)
    bias = {}
    for oc, ec in PAIRS:
        b = (m[oc] - m[ec]).groupby(m["month"]).mean()
        bias[ec] = b

    corr = era.copy()
    for oc, ec in PAIRS:
        corr[ec] = corr[ec] + corr["date"].dt.month.map(bias[ec])

    keep = ["date", "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
            "precipitation_sum", "relative_humidity_2m_mean", "et0_fao_evapotranspiration",
            "shortwave_radiation_sum", "sunshine_duration", "wind_speed_10m_max",
            "soil_moisture_0_to_7cm_mean"]
    corr[keep].to_csv(os.path.join(PROC, "daily_corrected.csv"), index=False, encoding="utf-8-sig")

    # 指标对比（原始 vs 订正）
    ri = indices.compute(era[keep])
    ci = indices.compute(corr[keep])
    def agg(x):
        return {y: (int(g["frost"].sum()), int(g["heat"].sum()), int(g["cold_shock"].sum()))
                for y, g in x.groupby("year")}

    md = ["# 台站偏差订正\n",
          "> 方法：用杭州站(58457)观测对 ERA5 做**逐月偏差订正**（corrected = ERA5 + 月偏差）。",
          "> 订正目标为城市观测站；与梅家坞山谷的残余差异属真实微气候，非误差。\n",
          "## 逐月偏差(℃) 观测−ERA5",
          "| 月份 | Tmin | Tmax | Tmean |",
          "|---|---|---|---|"]
    for mo in range(1, 13):
        md.append(f"| {mo} | {bias['temperature_2m_min'].get(mo, float('nan')):.2f} | "
                  f"{bias['temperature_2m_max'].get(mo, float('nan')):.2f} | "
                  f"{bias['temperature_2m_mean'].get(mo, float('nan')):.2f} |")
    md += ["\n## 指标变化（霜冻日 / 高温日 / 倒春寒）",
           "| 年份 | 原始(霜冻/高温/倒春寒) | 订正后 |", "|---|---|---|"]
    ao, ac = agg(ri), agg(ci)
    for y in sorted(ao):
        md.append(f"| {y} | {ao[y]} | {ac.get(y, '-')} |")
    md += ["\n> 订正后霜冻/高温日数变化，可用于敏感性分析；如需以订正数据跑模型，"
           "将 `data/processed/daily_corrected.csv` 替换 `daily.csv` 即可（pipeline 支持）。"]
    os.makedirs(REPORT, exist_ok=True)
    with open(os.path.join(REPORT, "station_correction.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md[:8]))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
        for ec, c in [("temperature_2m_min", "#4aa8ff"), ("temperature_2m_max", "#e08a3c")]:
            ax[0].plot(range(1, 13), [bias[ec].get(i, np.nan) for i in range(1, 13)], "o-", color=c, label=ec)
        ax[0].axhline(0, color="#8aa0b2", ls=":"); ax[0].set_xticks(range(1, 13))
        ax[0].set_title("逐月偏差(℃) 观测−ERA5"); ax[0].legend(fontsize=8)
        w = corr[(corr["date"] >= "2024-03-01") & (corr["date"] <= "2024-04-15")]
        e = era[(era["date"] >= "2024-03-01") & (era["date"] <= "2024-04-15")]
        ax[1].plot(e["date"], e["temperature_2m_min"], color="#4aa8ff", ls="--", label="ERA5 Tmin")
        ax[1].plot(w["date"], w["temperature_2m_min"], color="#4aa8ff", label="订正 Tmin")
        ax[1].plot(e["date"], e["temperature_2m_max"], color="#e08a3c", ls="--", label="ERA5 Tmax")
        ax[1].plot(w["date"], w["temperature_2m_max"], color="#e08a3c", label="订正 Tmax")
        ax[1].set_title("订正前后(2024 春季)"); ax[1].legend(fontsize=7)
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_correction.png"), dpi=120); plt.close(fig)
        print("-> report/figures/fig_correction.png")
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)
    print("-> data/processed/daily_corrected.csv, report/station_correction.md")


if __name__ == "__main__":
    main()
