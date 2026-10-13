"""
P1-5 改进：事件级回测 + 负事件 + 误报/提前量（滚动历史回放）。
诚实前提：真值仍为规则标签（弱标签），因此本报告区分"规则复现指标"与"业务指标"，
并**显式加入负事件窗口**以给出误报率，弥补此前只展示 7/7 正事件的不足。
输出 report/backtest_blind.md、report/figures/fig_blind.png
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")
FIGS = os.path.join(REPORT, "figures")

# 正事件（文档化，含来源）：(名称, 起, 止, 类型)
POS = [
    ("2016 初春寒潮", "2016-01-18", "2016-02-12", "frost"),
    ("2018 冬季冰冻", "2018-01-24", "2018-02-06", "frost"),
    ("2020-08 高温干旱", "2020-07-25", "2020-08-31", "heat"),
    ("2022 破纪录高温", "2022-07-10", "2022-08-31", "heat"),
    ("2024 盛夏高温", "2024-07-01", "2024-08-31", "heat"),
    ("2024 春季霜冻", "2024-03-01", "2024-04-05", "frost"),
    ("2025 倒春寒", "2025-03-01", "2025-04-10", "frost"),
]
# 负事件窗口（预期低风险：暖春/温和时段）
NEG = [
    ("2021 暖春后段", "2021-04-15", "2021-05-31"),
    ("2019 初夏温和", "2019-05-15", "2019-06-30"),
    ("2020 晚秋温和", "2020-10-15", "2020-11-20"),
]
HORIZON = 3          # 预警在事件前 3 天内的提前信号
BUILDUP = 0.3        # 提前信号阈值


def main():
    df = pd.read_csv(os.path.join(PROC, "predictions.csv"))
    df["date"] = pd.to_datetime(df["date"])
    df["haz"] = (df["risk_R"] >= 0.5).astype(int)
    total = len(df)
    base_rate = float(df["haz"].mean())

    # 事件级召回
    rows = []
    for name, s, e, kind in POS:
        w = df[(df["date"] >= s) & (df["date"] <= e)]
        hz = w[w["haz"] == 1]
        detected = len(hz) > 0
        peak = w.loc[w["risk_R"].idxmax()]
        # 提前量：事件峰值前 BUILDUP 信号首次出现
        pre = df[(df["date"] >= pd.Timestamp(s) - pd.Timedelta(days=HORIZON)) & (df["date"] < s)]
        lead = None
        if len(pre[pre["risk_R"] >= BUILDUP]):
            lead = int((pd.Timestamp(s) - pre[pre["risk_R"] >= BUILDUP]["date"].min()).days)
        rows.append({"name": name, "window": f"{s}~{e}", "detected": detected,
                     "hazard_days": int(len(hz)), "peak_R": round(float(peak["risk_R"]), 2),
                     "lead_days": lead if lead is not None else "-"})

    # 负事件：窗口内风险日比例（误报代理）
    neg_rows = []
    for name, s, e in NEG:
        w = df[(df["date"] >= s) & (df["date"] <= e)]
        neg_rows.append({"name": name, "window": f"{s}~{e}", "days": len(w),
                         "hazard_days": int(w["haz"].sum()),
                         "rate": round(float(w["haz"].mean()) if len(w) else 0.0, 3)})

    # 误报代理：文档化事件之外的"风险日"
    mask_in = np.zeros(total, dtype=bool)
    for name, s, e, kind in POS:
        mask_in |= ((df["date"] >= s) & (df["date"] <= e)).values
    out_days = df[(df["haz"] == 1) & (~mask_in)]
    hit_days = int(df[(df["haz"] == 1) & (mask_in)].shape[0])
    false_proxy = int(out_days.shape[0])

    detected = sum(1 for r in rows if r["detected"])
    leads = [r["lead_days"] for r in rows if isinstance(r["lead_days"], int) and r["lead_days"] >= 0]
    md = ["# 事件级回测 + 负事件 + 误报/提前量（滚动历史回放）\n",
          "> 真值仍为**规则弱标签**；本报告区分『规则复现指标』与『业务指标』，并**加入负事件**给出误报率。",
          "> 判定：窗口内出现风险日(risk_R≥0.5)即判命中；提前量=事件前 %d 天内首次出现 risk_R≥%.1f 的天数。" % (HORIZON, BUILDUP),
          "",
          "## 1) 正事件（事件级）",
          "| 事件 | 窗口 | 命中 | 风险日 | 峰值R | 提前量(天) |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['name']} | {r['window']} | {'✅' if r['detected'] else '❌'} | {r['hazard_days']} | {r['peak_R']} | {r['lead_days']} |")
    md += ["", f"- **事件召回 = {detected}/{len(rows)} = {detected/len(rows)*100:.0f}%**；"
               f"平均提前量 ≈ {np.mean(leads):.1f} 天（n={len(leads)}）" if leads else "",
           "",
           "## 2) 负事件窗口（预期低风险，用于误报率）",
           "| 负事件窗口 | 天数 | 风险日 | 窗口风险日比例 |", "|---|---|---|---|"]
    for r in neg_rows:
        md.append(f"| {r['name']} | {r['days']} | {r['hazard_days']} | {r['rate']} |")
    neg_rate = float(np.mean([r["rate"] for r in neg_rows])) if neg_rows else 0.0
    md += ["", f"- 负事件窗口平均风险日比例 ≈ **{neg_rate*100:.0f}%**（越低越好）。",
           "",
           "## 3) 误报代理（全期）",
           f"- 全期风险日基准率（risk_R≥0.5 占比）= **{base_rate*100:.1f}%**（{int(df['haz'].sum())}/{total} 天）。",
           f"- 落在**文档化事件窗口内**的风险日：{hit_days}；**窗口外**：{false_proxy}。",
           "- 说明：**窗口外 ≠ 必然是误报**（可能存在未文档化的真实风险），故称『误报代理』。",
           "",
           "## 4) 结论（诚实）",
           "- 本框架把『规则复现』与『业务验证』分开：事件召回高属预期；**关键待补是与真实受灾/减产/品质的对照**。",
           "- 下一步（第二阶段）：用真实开采日/受灾/产量标签替换弱标签，预注册事件清单，开展**盲测**并报告 precision/recall、误报天数、有效提前量。"]
    md = [x for x in md if x != ""]
    os.makedirs(REPORT, exist_ok=True)
    open(os.path.join(REPORT, "backtest_blind.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
        ax[0].bar([r["name"][:10] for r in rows], [r["hazard_days"] for r in rows], color="#4aa8ff")
        ax[0].set_title("正事件：窗口内风险日数"); ax[0].tick_params(axis="x", rotation=45, labelsize=8)
        ax[1].bar([r["name"][:10] for r in neg_rows], [r["rate"] for r in neg_rows], color="#e5534b")
        ax[1].set_title("负事件：风险日比例（误报代理）"); ax[1].tick_params(axis="x", rotation=30, labelsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_blind.png"), dpi=120); plt.close(fig)
        print("-> report/figures/fig_blind.png")
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)
    print("-> report/backtest_blind.md")


if __name__ == "__main__":
    main()