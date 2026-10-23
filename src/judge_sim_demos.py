"""评委模拟（全 53 项目 + 关键对手的 Demo/README 证据）。

与上一版的区别：对 12 个主要对手补了 2–3 句来自 README/Demo 的事实证据，
包括它们自己写明的限制（例如 CoralBleach 的合成数据、ThawGuard 不做灾前预测），
避免"只凭一行标题"高估或低估。
"""
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import decision_client  # noqa: E402
import judge_sim as J  # noqa: E402
import judge_sim_full as F  # noqa: E402

# 名称 → 从 README/Demo 抽取的事实（2–3 句）
ENRICH = {
    "丹橘知旱": "柑橘，丹江口库区约 10 万果农；GitHub Pages 在线 Demo + 仓库；园块→物候识别+四类风险+农事建议+自然语言问答；2022 高温首个“重”级提示比 40.9℃ 峰值提前 3 天；有历史回测。",
    "CityOS": "面向宁波/台州/温州/杭州四城；统一数据契约（来源、许可、观测时间、证据类型）；实时分析+历史回放+情景预演+人工复核建议；仓库+GitHub Pages；主要用户是政府部门。",
    "微气候智能体": "76 年 ERA5-Land 训练；0–72 小时逐小时气温 + P10–P90 区间；LightGBM 微气候模型；接入 GLM-4-Flash 生成农事建议并支持多轮问答；Web 仪表盘；仓库 365 文件；冷启动偶发超时。",
    "CoralBleach": "珊瑚白化预测预警科研台；地图/站点/序列/随访值全部为合成演示；README 明确写“没有接入真实 NOAA 数据，也没有证明全球预测能力”；仓库+Demo。",
    "一垄一候": "10 m 地块级降尺度；README 主张“风险预警→行动决策”闭环；但 Demo 是 2.4MB 单文件静态看板，无后端、无问答；仓库仅 2 次提交。",
    "RainWise": "深圳罗湖往返出行；分别设置去程/返程；给出运营限制、地点隐患、天气参考与集合成员超阈值比例；保留公开来源与时间；仓库+线上站。",
    "ReefTriage": "仙本那 28 个礁段周级优先级；NOAA DHW + Copernicus Marine + ETOPO + HYCOM 粒子追踪；ML 白化预测 + 熵权 TOPSIS；仓库；Demo 仅视频。",
    "ThawGuard": "青藏高原热融滑塌历史核查；README 明确“不提供灾前预测或正式预警”；面向科研判读人员；离线演示包。",
    "塞上绿色长城": "西北五省县域治理优先级；LightGBM + CA-Markov；离线可运行（index.html）；仓库；站点当前连接失败。",
    "治沙选址": "西北荒漠化易发性制图；全开源管线；空间交叉验证；仓库；无在线 Demo。",
    "TeaWatch": "35 年逐日数据推龙井开采日；自述对官方开采日 MAE 1.8 天；Demo 为静态单页（预计算数据 + Chart.js）；无仓库、无地块查询、无行动清单。",
    "微气候智能体": "76 年 ERA5-Land；0–72h 逐小时 P10–P90；LightGBM；GLM-4-Flash 农事建议+多轮问答；Web 仪表盘；仓库；冷启动偶发超时。",
}

SELF = ("TeaWindow（梅坞采候）：梅家坞地块级复合风险（霜冻×高温×干旱）+ 白话行动 + 问答 + 可打印体检卡；"
        "1+5 护栏（数据体检 + StartLux 放行/事实核对，最多 2 轮，fail-open）；"
        "官方开采日不拟合 MAE 1.8 天、前向 2.67 天；冻结评估集 AUC 0.998/F1 0.85；"
        "开源 159 提交、155 tests；线上 Demo 冷启动 3 秒快照兜底；无真实用户、无田间产量真值。")


def main():
    if not decision_client.enabled():
        print("STARTLUX_API_KEY not set")
        return 1
    field = []
    for name, line in F.FIELD:
        field.append({"name": name, "evidence": ENRICH.get(name, line)})
    state = {"self": SELF, "field": field, "field_size": len(field) + 1,
             "instruction": "这是专区去重后的全部 53 个项目；主要对手给了 README/Demo 事实，其余为一行摘要。"
                            "只依据写出的证据判断，未写出的能力按不存在处理。"}

    score_q = {k: J.QUESTIONS[k] for k in J.WEIGHTS}
    meta_q = {k: J.QUESTIONS[k] for k in ("top30", "pilot", "award")}
    meta_q.update(F.BAND)

    def call(q, label):
        for i in range(4):
            try:
                return decision_client.decide(state, q, think_mode="auto", gate=0.9, timeout=120)
            except Exception as e:  # noqa: BLE001
                print(f"[{label}] 重试 {i+1}", repr(e)[:80], flush=True)
                time.sleep(3)
        return None

    a = call(score_q, "score")
    if not a:
        print("startlux unavailable")
        return 1
    ans = dict(a.get("answers") or {})
    b = call(meta_q, "meta")
    if b:
        ans.update(b.get("answers") or {})

    rows, total = [], 0.0
    for k, w in J.WEIGHTS.items():
        pts = J._expected(ans.get(k) or {})
        total += pts * w
        rows.append((J.NAMES[k], w, round(pts, 1)))
    award = (ans.get("award") or {}).get("probabilities") or {}
    band = (ans.get("tier") or {}).get("probabilities") or {}
    best = max(award, key=lambda x: award[x]) if award else "-"
    band_best = max(band, key=lambda x: band[x]) if band else "-"

    lines = ["# 评委模拟（53 项目，含 12 个对手的 README/Demo 证据）", "",
             f"- 加权总分：**{total:.1f} / 100**", "",
             "| 维度 | 权重 | 分数 |", "|---|---:|---:|"]
    for name, w, pts in rows:
        lines.append(f"| {name} | {int(w*100)}% | {pts} |")
    lines += ["", f"- 最可能档位：**{band_best}**",
              f"- 进前 30：**{float((ans.get('top30') or {}).get('noul') or 0):.3f}**"
              f" ｜ 进决赛 12：**{float((ans.get('final12') or {}).get('noul') or 0):.3f}**"
              f" ｜ 90 天 pilot：**{float((ans.get('pilot') or {}).get('noul') or 0):.3f}**",
              f"- 最可能奖项：**{best}**", "", "| 档位 | 概率 |", "|---|---:|"]
    for k, v in sorted(band.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", "| 奖项 | 概率 |", "|---|---:|"]
    for k, v in sorted(award.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", "> 仍为模拟；主要价值是相对短板，不是绝对分数。"]

    out = os.path.join(ROOT, "report", "judge_sim_demos.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
