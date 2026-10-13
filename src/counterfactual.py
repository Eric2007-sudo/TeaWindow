"""
新颖点 N2：反事实归因——量化"如果做了防护"的减损效果。
对比实际风险度 vs 反事实（灌溉/遮阳/覆盖）风险度，回答"若不上遮阳/未灌溉会怎样"。
输出 report/counterfactual.md、report/figures/fig_counterfactual.png
"""
import os
import sys

import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from model import rubric  # noqa: E402

ROOT = os.path.dirname(SRC)
PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")
FIGS = os.path.join(REPORT, "figures")

HEAT_WIN = ("2022-07-10", "2022-08-31")
FROST_WIN = ("2024-03-01", "2024-04-05")


def _risk(df):
    return np.asarray(rubric(df)[1], dtype=float)


def main():
    df = pd.read_csv(os.path.join(PROC, "daily.csv"))
    df["date"] = pd.to_datetime(df["date"])

    # 高温窗口：反事实=灌溉/遮阳（土壤湿度恢复、水分亏缺下降）
    h = df[(df["date"] >= HEAT_WIN[0]) & (df["date"] <= HEAT_WIN[1])].copy()
    h_act = _risk(h)
    h_cf = h.copy()
    h_cf["soil_moisture_0_to_7cm_mean"] = np.maximum(h_cf["soil_moisture_0_to_7cm_mean"], 0.35)
    h_cf["water_deficit_10d"] = h_cf["water_deficit_10d"] * 0.3
    h_cfr = _risk(h_cf)

    # 霜冻窗口：反事实=覆盖/熏烟（最低温抬升 1.5℃）
    f = df[(df["date"] >= FROST_WIN[0]) & (df["date"] <= FROST_WIN[1])].copy()
    f_act = _risk(f)
    f_cf = f.copy()
    f_cf["temperature_2m_min"] = f_cf["temperature_2m_min"] + 1.5
    f_cfr = _risk(f_cf)

    def summarize(a, c, win, name):
        haz_a = int((a >= 0.5).sum()); haz_c = int((c >= 0.5).sum())
        return {"name": name, "win": f"{win[0]}~{win[1]}",
                "mean_actual": round(float(a.mean()), 2), "mean_cf": round(float(c.mean()), 2),
                "reduction_pct": round(float((a.mean() - c.mean()) / (a.mean() + 1e-9) * 100), 1),
                "hazard_days_actual": haz_a, "hazard_days_cf": haz_c,
                "avoided": haz_a - haz_c}

    s_heat = summarize(h_act, h_cfr, HEAT_WIN, "高温干旱 · 反事实=灌溉/遮阳")
    s_frost = summarize(f_act, f_cfr, FROST_WIN, "春季霜冻 · 反事实=覆盖/熏烟(+1.5℃)")

    md = ["# 反事实归因：防护能减多少风险\n",
          "> 方法：在实测气象上，将**防护措施**体现为输入改变（灌溉→土壤湿度恢复；覆盖→最低温+1.5℃），",
          "> 用同一风险规则重算，比较风险度与风险日变化。\n",
          "| 场景 | 窗口 | 实际均值 | 防护后均值 | 风险降低 | 风险日(实际→防护) | 避免风险日 |",
          "|---|---|---|---|---|---|---|"]
    for s in (s_heat, s_frost):
        md.append(f"| {s['name']} | {s['win']} | {s['mean_actual']} | {s['mean_cf']} | "
                  f"**−{s['reduction_pct']}%** | {s['hazard_days_actual']} → {s['hazard_days_cf']} | **{s['avoided']}** |")
    md += ["\n## 解读",
           f"- **高温干旱**：及时灌溉+遮阳，可把窗口内平均风险度降低约 **{s_heat['reduction_pct']}%**，避免 **{s_heat['avoided']}** 个风险日。",
           f"- **春季霜冻**：覆盖/熏烟（最低温+1.5℃），可降低约 **{s_frost['reduction_pct']}%**，避免 **{s_frost['avoided']}** 个风险日。",
           "- 意义：**把'要不要防护'变成可量化的收益陈述**（对应下方价值闭环）。",
           "\n> 注：反事实为**模型内情景分析**（输入扰动），用于相对比较，非田间实测因果结论。"]
    os.makedirs(REPORT, exist_ok=True)
    open(os.path.join(REPORT, "counterfactual.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
        ax[0].plot(h["date"], h_act, color="#e5534b", label="实际风险度")
        ax[0].plot(h["date"], h_cfr, color="#3fb950", ls="--", label="灌溉/遮阳后")
        ax[0].set_title("高温干旱窗口（2022）"); ax[0].legend(fontsize=8)
        ax[1].plot(f["date"], f_act, color="#4aa8ff", label="实际风险度")
        ax[1].plot(f["date"], f_cfr, color="#3fb950", ls="--", label="覆盖/熏烟后")
        ax[1].set_title("春季霜冻窗口（2024）"); ax[1].legend(fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_counterfactual.png"), dpi=120); plt.close(fig)
        print("-> report/figures/fig_counterfactual.png")
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)
    print("-> report/counterfactual.md")


if __name__ == "__main__":
    main()
