"""
新颖点 N5：价值闭环——把风险转成"预期损失 / 保险保费 / 认养权益"。
收益锚点来自公开资料（茶叶气象指数保险：保额500元/亩、费率2%、保费10元/亩）。
读取 predictions.csv 估计事件年频率；注入 web/data.json 的 data["value"]。
输出 report/value_chain.md
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
WEB = os.path.join(ROOT, "web")
REPORT = os.path.join(ROOT, "report")

# —— 假设（示意，明确标注）——
YIELD_JIN_PER_MU = 20.0      # 亩产干茶(斤)，示意
PRICE_PER_JIN = 800.0        # 均价(元/斤)，示意
LOSS_FROST = 0.30            # 霜冻致损率
LOSS_HEAT = 0.30             # 高温致损率
INSURED_SUM_PER_MU = 500.0   # 参考：茶叶种植保险保额(元/亩)
INSURANCE_RATE = 0.02        # 参考：费率
MARKUP_FOR_GROWER = 1.2      # 增产/保价系数（提供工具带来的价值上限示意）


def main():
    df = pd.read_csv(os.path.join(PROC, "predictions.csv"))
    df["date"] = pd.to_datetime(df["date"])
    g = df.groupby("year").agg(cold=("cold_shock", "sum"), frost=("frost", "sum"),
                               heat=("heat", "sum"), hsev=("heat_severe", "sum")).reset_index()
    yrs = g["year"].tolist()
    frost_years = (g["cold"] >= 5).sum()
    heat_years = ((g["heat"] >= 20) | (g["hsev"] >= 5)).sum()
    p_frost = frost_years / len(g)
    p_heat = heat_years / len(g)

    value_per_mu = YIELD_JIN_PER_MU * PRICE_PER_JIN
    exp_loss = (p_frost * LOSS_FROST + p_heat * LOSS_HEAT) * value_per_mu
    premium = INSURED_SUM_PER_MU * INSURANCE_RATE
    # 工具价值：把两类风险各降低约 20%（通过及时抢采/防护，示意）
    tool_benefit = 0.2 * exp_loss
    adoption_adj = value_per_mu * (MARKUP_FOR_GROWER - 1)

    md = ["# 价值闭环（风险 → 预期损失 → 保费 → 认养）\n",
          "> 说明：以下为**示意性测算**，参数为公开锚点或合理假设，用于说明商业模式逻辑。\n",
          "## 事件频率（2015–2026 实测）",
          f"- 霜冻致损年：**{int(frost_years)}/{len(g)} ≈ {p_frost*100:.0f}%**",
          f"- 高温致损年：**{int(heat_years)}/{len(g)} ≈ {p_heat*100:.0f}%**\n",
          "## 每亩价值测算（示意）",
          f"- 亩产值 ≈ {YIELD_JIN_PER_MU:.0f} 斤 × {PRICE_PER_JIN:.0f} 元/斤 = **{value_per_mu:,.0f} 元**",
          f"- 期望损失 ≈ (霜冻 {p_frost*100:.0f}%×{LOSS_FROST:.0%} + 高温 {p_heat*100:.0f}%×{LOSS_HEAT:.0%}) × 亩产值 = **{exp_loss:,.0f} 元/亩·年**",
          f"- 参考保费：保额 {INSURED_SUM_PER_MU:.0f} 元/亩 × 费率 {INSURANCE_RATE:.0%} = **{premium:.0f} 元/亩**（远低于期望损失，说明对冲价值大）",
          f"- **工具减损价值**（及时抢采/防护，降损约 20%）≈ **{tool_benefit:,.0f} 元/亩·年**\n",
          "## 商业模式含义",
          f"- 对茶农：花 {premium:.0f} 元保费/或订阅工具，可对冲约 {exp_loss:,.0f} 元/亩的期望损失；",
          f"- 对合作社/茶企：以 '每地块 ¥299–999/年' 订阅即划算（见 `submit/06_商业模式.md`）；",
          "- 对保险：TeaWindow 输出高风险地块 → 精准定价与减损；",
          "- 对认养/共享茶园：按地块风险等级设定**权益/折扣**（高风险地块提供技术辅导）。\n",
          "> 数据锚点：茶叶种植保险 保额500元/亩·费率2%·保费10元/亩；台风/低温指数险案例（见研究资料）。"]

    os.makedirs(REPORT, exist_ok=True)
    open(os.path.join(REPORT, "value_chain.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))

    data = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
    data["value"] = {"p_frost": round(float(p_frost), 2), "p_heat": round(float(p_heat), 2),
                     "value_per_mu": value_per_mu, "expected_loss_per_mu": round(exp_loss, 0),
                     "premium_per_mu": premium, "tool_benefit_per_mu": round(tool_benefit, 0),
                     "assumptions": {"yield_jin_per_mu": YIELD_JIN_PER_MU, "price_per_jin": PRICE_PER_JIN,
                                     "loss_frost": LOSS_FROST, "loss_heat": LOSS_HEAT}}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
    open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
    print("-> report/value_chain.md (+注入 web/data.json)")


if __name__ == "__main__":
    main()
