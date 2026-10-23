"""评委模拟（带竞争场）：把主要对手放进 state，再让 StartLux 打分。

为什么需要这一版：只给自家证据时，模型会给出过高的获奖概率（0.33 最佳气候、0.23 全场大奖），
因为它不知道场上还有谁。加入 6 个主要对手后，奖项判断才有参照。
"""
import json
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import decision_client  # noqa: E402
import judge_sim as J  # noqa: E402

FIELD = [
    {"name": "丹橘知旱", "track": "农业", "evidence": "柑橘 10 万果农；在线 Demo；园块→物候+四类风险+建议+问答；2022 高温提前 3 天；开源。"},
    {"name": "CityOS", "track": "内涝", "evidence": "省域台风内涝世界模型；开源+Pages；数据许可/时效/证据类型标注完整；面向政府。"},
    {"name": "微气候智能体", "track": "茶", "evidence": "72h P10–P90；30m 六图层；传感器；后端 API；GitHub 365 文件；冷启动偶发超时。"},
    {"name": "CoralBleach-Agent", "track": "珊瑚", "evidence": "珊瑚白化可核查科研流程；开源+Demo；面向科研。"},
    {"name": "一垄一候", "track": "茶", "evidence": "10m 降尺度地块看板；开源；静态无后端；无行动输出。"},
    {"name": "TeaWatch", "track": "茶", "evidence": "35 年数据；官方开采日 MAE 1.8 天；静态单页；无仓库；无地块查询。"},
]


def main():
    if not decision_client.enabled():
        print("STARTLUX_API_KEY not set")
        return 1
    state = dict(J.STATE)
    state["field"] = FIELD
    state["instruction"] = "请在这 7 个项目的竞争场中判断；不要只看本项目。"

    score_q = {k: J.QUESTIONS[k] for k in J.WEIGHTS}
    meta_q = {k: J.QUESTIONS[k] for k in ("top30", "pilot", "award")}

    out = None
    for i in range(4):
        try:
            out = decision_client.decide(state, score_q, think_mode="auto", gate=0.9, timeout=90)
            break
        except Exception as e:  # noqa: BLE001
            print("[field] 重试", i + 1, repr(e)[:80], flush=True)
            time.sleep(3)
    if not out:
        print("startlux unavailable")
        return 1
    ans = dict(out.get("answers") or {})
    for i in range(3):
        try:
            meta = decision_client.decide(state, meta_q, think_mode="auto", gate=0.9, timeout=90)
            ans.update(meta.get("answers") or {})
            break
        except Exception as e:  # noqa: BLE001
            print("[field] meta 重试", i + 1, repr(e)[:80], flush=True)
            time.sleep(3)

    rows, total = [], 0.0
    for k, w in J.WEIGHTS.items():
        pts = J._expected(ans.get(k) or {})
        total += pts * w
        rows.append((J.NAMES[k], w, round(pts, 1)))
    top30 = float((ans.get("top30") or {}).get("noul") or 0.0)
    pilot = float((ans.get("pilot") or {}).get("noul") or 0.0)
    award_probs = (ans.get("award") or {}).get("probabilities") or {}
    best = max(award_probs, key=lambda x: award_probs[x]) if award_probs else "-"

    lines = ["# 评委模拟（含竞争场，StartLux）", "",
             f"- 竞争场：本项目 + 6 个主要对手（丹橘知旱 / CityOS / 微气候 / CoralBleach / 一垄一候 / TeaWatch）",
             f"- 加权总分：**{total:.1f} / 100**", "",
             "| 维度 | 权重 | 分数 |", "|---|---:|---:|"]
    for name, w, pts in rows:
        lines.append(f"| {name} | {int(w*100)}% | {pts} |")
    lines += ["", f"- 进前 30 概率：**{top30:.3f}**",
              f"- 90 天 pilot：**{pilot:.3f}**",
              f"- 最可能奖项：**{best}**", "", "| 奖项 | 概率 |", "|---|---:|"]
    for k, v in sorted(award_probs.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", "> 仍是模拟：只用于找相对短板，不能当官方预测。"]

    os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
    p = os.path.join(ROOT, "report", "judge_sim_field.md")
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("->", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
