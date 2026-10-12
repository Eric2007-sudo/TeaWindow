"""
生成分析报告图表 -> report/figures/*.png
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
FIGS = os.path.join(ROOT, "report", "figures")
os.makedirs(FIGS, exist_ok=True)

df = pd.read_csv(os.path.join(PROC, "predictions.csv"))
df["date"] = pd.to_datetime(df["date"])
fc = pd.read_csv(os.path.join(PROC, "daily_forecast.csv"))
fc["date"] = pd.to_datetime(fc["date"])

# 1) 年度风险统计
y = df.groupby("year").agg(frost=("frost", "sum"), heat=("heat", "sum"),
                           cold=("cold_shock", "sum"), hazard=("hazard", "sum")).reset_index()
fig, ax = plt.subplots(figsize=(8, 4))
w = 0.2
ax.bar(y.year - 1.5 * w, y.frost, w, label="霜冻日", color="#4aa8ff")
ax.bar(y.year - 0.5 * w, y.cold, w, label="倒春寒", color="#d6b657")
ax.bar(y.year + 0.5 * w, y.heat, w, label="高温日", color="#e5534b")
ax.bar(y.year + 1.5 * w, y.hazard, w, label="复合风险日", color="#3fb950")
ax.set_title("梅家坞逐年气候风险统计（2015–2026）")
ax.set_xlabel("年份"); ax.set_ylabel("天数"); ax.legend(ncol=4, fontsize=8)
fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_yearly.png")); plt.close(fig)

# 2) 2026 风险与适宜度时间线 + 预报
recent = df[df.year == 2026]
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(recent.date, recent.risk_R, color="#e5534b", label="综合风险度 R")
ax.plot(recent.date, recent.suitability / 100, color="#3fb950", label="采摘适宜度(归一)")
ax.axvline(pd.Timestamp("2026-10-11"), color="#8aa0b2", ls="--", lw=1)
ax.axvspan(recent.date.min(), pd.Timestamp("2026-10-11"), color="#4aa8ff", alpha=0.05)
ax.set_title("2026 年综合风险度与采摘适宜度（虚线右侧为预报推导期）")
ax.legend(fontsize=8); fig.tight_layout()
fig.savefig(os.path.join(FIGS, "fig_risk2026.png")); plt.close(fig)

# 3) 特征重要性
with open(os.path.join(ROOT, "models", "metrics.json"), encoding="utf-8") as f:
    met = json.load(f)
imp = met["permutation_importance_top"]
names = list(imp.keys())[::-1]; vals = [imp[k] for k in names]
fig, ax = plt.subplots(figsize=(7, 4))
ax.barh(names, vals, color="#4aa8ff")
ax.set_title("特征重要性（置换法，测试集 AUC 下降）")
fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_importance.png")); plt.close(fig)

# 4) NDVI 与气温
with open(os.path.join(PROC, "ndvi.json"), encoding="utf-8") as f:
    nv = json.load(f)["series"]
nd = pd.DataFrame(nv); nd["date"] = pd.to_datetime(nd["date"]); nd = nd.set_index("date")
t = df.set_index("date")["temperature_2m_max"]
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(nd.index, nd.ndvi, color="#3fb950", marker="o", ms=3, label="MODIS NDVI(近似)")
ax.set_ylabel("NDVI", color="#3fb950")
ax2 = ax.twinx()
mm = t.resample("MS").mean()
ax2.plot(mm.index, mm.values, color="#e08a3c", label="月均 Tmax")
ax2.set_ylabel("Tmax (°C)", color="#e08a3c")
ax.set_title("植被活力(NDVI) 与气温（2025-02 起，遥感为近似反演）")
fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_ndvi_temp.png")); plt.close(fig)

# 5) 2024 春季霜冻案例
case = df[(df.date >= "2024-03-01") & (df.date <= "2024-04-15")]
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(case.date, case.temperature_2m_max, color="#e08a3c", label="Tmax")
ax.plot(case.date, case.temperature_2m_min, color="#4aa8ff", label="Tmin")
ax.scatter(case[case.frost == 1].date, case[case.frost == 1].temperature_2m_min,
           color="#1e5fd0", zorder=5, label="霜冻日")
ax.scatter(case[case.cold_shock == 1].date, case[case.cold_shock == 1].temperature_2m_min,
           color="#d6b657", marker="^", s=60, zorder=5, label="倒春寒")
ax.axhline(2, color="#8aa0b2", ls=":", lw=1)
ax.set_title("2024 春季霜冻/倒春寒案例（梅家坞）")
ax.legend(fontsize=8); fig.tight_layout()
fig.savefig(os.path.join(FIGS, "fig_frost2024.png")); plt.close(fig)

# 6) 高温案例（2022 与 2026 夏季）
for yr in (2022, 2026):
    c = df[(df.date >= f"{yr}-07-01") & (df.date <= f"{yr}-08-31")]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(c.date, c.temperature_2m_max, color="#e5534b", label="Tmax")
    ax.axhline(35, color="#8aa0b2", ls=":", lw=1)
    ax.fill_between(c.date, 35, c.temperature_2m_max, where=c.temperature_2m_max >= 35,
                    color="#e5534b", alpha=0.25)
    ax.set_title(f"{yr} 年盛夏高温（≥35℃ 阴影）与水分亏缺背景")
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(os.path.join(FIGS, f"fig_heat{yr}.png")); plt.close(fig)

print("figures ->", os.listdir(FIGS))
