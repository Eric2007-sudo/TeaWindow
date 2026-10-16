"""
新颖点 N6：天气指数保险触发（借鉴获奖方向"天气指数保险精准理赔"）。
把气候风险转成**客观指数**（春霜冻度日 / 夏热日数），按规则触发赔付，
并计算历史赔付年与精算公平保费。注入 web/data.json 的 data["insurance"]。
输出 report/index_insurance.md、report/figures/fig_insurance.png
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
WEB = os.path.join(ROOT, "web")
REPORT = os.path.join(ROOT, "report")
FIGS = os.path.join(REPORT, "figures")

PAYOUT_FROST = 1600.0   # 元/亩（参考：倒春寒霜冻每亩赔约1600元）
PAYOUT_HEAT = 1000.0    # 元/亩（示意）


def main():
    df = pd.read_csv(os.path.join(PROC, "predictions.csv"))
    df["date"] = pd.to_datetime(df["date"])
    rows = []
    for y, g in df.groupby("year"):
        spring = g[g["month"].isin([2, 3])]
        summer = g[g["month"].isin([7, 8])]
        frost_idx = float(np.clip(4 - spring["temperature_2m_min"], 0, None).sum())
        heat_idx = float((summer["temperature_2m_max"] >= 37).sum())
        rows.append({"year": int(y), "frost_index": round(frost_idx, 1), "heat_index": heat_idx})
    idx = pd.DataFrame(rows).sort_values("year")

    # 历史样本不足（如归档退化到近 180 天）时，不输出 0 假值，明确标注样本不足
    if len(idx) < 5:
        data = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
        data["insurance"] = {"insufficient_history": True, "n_years": len(idx),
                             "note": "历史样本不足（<5 年），暂不给出指数保险定价；需先恢复完整历史归档。"}
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
        open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
        print("-> 历史样本不足（n_years=%d），已标注不给出定价" % len(idx))
        return

    tf = float(np.percentile(idx["frost_index"], 60))
    th = float(np.percentile(idx["heat_index"], 60))
    idx["frost_trigger"] = idx["frost_index"] > tf
    idx["heat_trigger"] = idx["heat_index"] > th
    idx["payout"] = idx["frost_trigger"] * PAYOUT_FROST + idx["heat_trigger"] * PAYOUT_HEAT
    fair_premium = float(idx["payout"].mean())
    fire = int((idx["payout"] > 0).sum())

    md = ["# 天气指数保险触发（客观指数 → 自动赔付）\n",
          "> 思路（借鉴获赛事方向）：不依赖人工查勘，用**客观气候指数**触发赔付。",
          f"> 春霜冻指数 = Σ max(0, 4−Tmin)（2–3 月，度日）；夏热指数 = 7–8 月 Tmax≥37℃ 日数。",
          f"> 触发阈值（P60）：霜冻 {tf:.0f} 度日 / 高温 {th:.0f} 天；赔付：霜冻 {PAYOUT_FROST:.0f} 元/亩，高温 {PAYOUT_HEAT:.0f} 元/亩。\n",
          "| 年份 | 霜冻指数 | 高温指数 | 是否赔付 | 赔付(元/亩) |", "|---|---|---|---|---|"]
    for _, r in idx.iterrows():
        trig = ("霜冻" if r["frost_trigger"] else "") + ("高温" if r["heat_trigger"] else "") or "—"
        md.append(f"| {r['year']} | {r['frost_index']} | {int(r['heat_index'])} | {trig} | {r['payout']:.0f} |")
    md += [f"\n- 历史赔付年：**{fire}/{len(idx)}**；年均赔付（精算公平保费）≈ **{fair_premium:.0f} 元/亩**。",
           f"- 参考政策保费约 10 元/亩（保额 500 元）——**指数保险的公平保费显著高于现行政策性低价**，",
           "  说明：① 政府补贴空间大；② 商业指数保险有定价空间。TeaWindow 的**地块级指数**可支持**差异化定价与自动理赔**。",
           "\n> 说明：赔付规则为示意；实际需与保险条款、气象站基准与监管口径对齐。"]
    os.makedirs(REPORT, exist_ok=True)
    open(os.path.join(REPORT, "index_insurance.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(idx["year"], idx["frost_index"], color="#4aa8ff", label="春霜冻指数(度日)")
        ax2 = ax.twinx(); ax2.plot(idx["year"], idx["payout"], "o-", color="#e5534b", label="赔付(元/亩)")
        ax.axhline(tf, color="#4aa8ff", ls=":", lw=1)
        ax.set_title("天气指数保险：指数与赔付（2015–2026）"); ax.set_ylabel("霜冻指数")
        ax2.set_ylabel("赔付(元/亩)"); ax.legend(fontsize=8, loc="upper left"); ax2.legend(fontsize=8, loc="upper right")
        fig.tight_layout(); fig.savefig(os.path.join(FIGS, "fig_insurance.png"), dpi=120); plt.close(fig)
        print("-> report/figures/fig_insurance.png")
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)

    data = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
    data["insurance"] = {"frost_threshold": round(tf, 0), "heat_threshold": round(th, 0),
                         "payout_frost": PAYOUT_FROST, "payout_heat": PAYOUT_HEAT,
                         "fair_premium_per_mu": round(fair_premium, 0), "fire_years": fire, "n_years": len(idx),
                         "series": idx[["year", "frost_index", "heat_index", "payout"]].to_dict("records")}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
    open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
    print("-> report/index_insurance.md (+注入 web/data.json)")


if __name__ == "__main__":
    main()
