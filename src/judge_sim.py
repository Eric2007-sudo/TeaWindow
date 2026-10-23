"""用 StartLux 按官方六维权重模拟评委打分（研究用途，非官方结果）。

输出：
  report/judge_sim.md

说明：
- 六维各给一个 0–100 的等级判断（5 档），加权求和；
- 另问：进前 30、获奖类别、是否值得进入 90 天 pilot；
- StartLux 是决策模型，不是评委；结果只用于自查"哪一维最弱"，不作对外宣称。
"""
import json
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import decision_client  # noqa: E402

WEIGHTS = {
    "problem": 0.20, "ai": 0.20, "feasible": 0.20,
    "market": 0.15, "communication": 0.15, "openness": 0.10,
}
NAMES = {
    "problem": "真实问题与气候价值",
    "ai": "AI 方案与技术有效性",
    "feasible": "可实施性与用户体验",
    "market": "市场可持续性",
    "communication": "传播与公众采用",
    "openness": "扩展性、伦理与开放性",
}
LEVELS = ["弱（0–20）", "较弱（20–40）", "中（40–60）", "较强（60–80）", "强（80–100）"]
MID = [10, 30, 50, 70, 90]

STATE = {
    "project": "TeaWindow（梅坞采候）",
    "track": "Track 01 梅家坞气候智慧茶园",
    "problem": "梅家坞龙井 43 号春季倒春寒、夏季高温干旱、连阴雨；茶农每天要判断采/防/灌。",
    "data": "ERA5 + MET Norway 双源；Sentinel-2 NDVI；30m DEM 地形下推；OSM 参考边界（非权属）。",
    "model": "numpy GBDT 复合风险（霜冻×高温×干旱）；冻结评估集 2024-01-01→2026-10-10，AUC 0.998、F1 0.85；单阈值基线 0.78/0.50。",
    "external_validation": "官方开采日（2022–2026）：不拟合参数 MAE 1.8 天；前向验证 2.67 天。",
    "demo": "在线可运行：点选任意地块→海拔/坡度/坡向+下推 Tmin/Tmax+风险 R+白话建议；可追问；可打印体检卡；冷启动 3 秒快照兜底。",
    "accountability": "1+5 护栏：自研生成 → 数据体检 → StartLux 放行与事实核对 → 有界修复（≤2 轮）；fail-open，不改数，不越权。",
    "openness": "MIT 代码 + CC BY 4.0 数据说明；GitHub 159 commits；155 tests；数据版本含上游 URL、参数、SHA-256。",
    "market": "B2B2C：合作社/茶企订阅 + 天气指数保险定价支持 + 园区/政府采购；CPU 可运行，边际成本低；目前无付费客户。",
    "limits": "无田间产量真值；示例传感器仅坐标未接硬件；OSM 边界为参考；学生团队首次参赛。",
    "evidence_page": "线上 /evidence.html 展示冻结评估集、混淆矩阵、官方开采日验证与数据血缘。",
}

QUESTIONS = {k: {"type": "score", "instructions": f"按官方维度「{NAMES[k]}」给这个项目打分（0–100）。",
                 "criteria": LEVELS} for k in WEIGHTS}
QUESTIONS.update({
    "top30": {"type": "noul", "instructions": "该项目是否足以进入前 30 支团队（初赛不超过 30 支）？"},
    "pilot": {"type": "noul", "instructions": "该项目是否值得进入赛后 90 天真实场景验证（仅 2–3 个名额）？"},
    "award": {"type": "choice", "instructions": "若进入决赛，最可能获得哪个奖项？",
              "criteria": {"全场大奖": "综合第一", "最佳气候解决方案": "气候价值突出",
                           "最佳科学传播": "传播设计突出", "最具市场潜力": "商业闭环清晰",
                           "青年潜力": "学生/首次参赛", "仅年度方案": "入围但无单项奖",
                           "未获奖": "未进入年度 12 项"}},
})


def _expected(ans):
    probs = ans.get("probabilities") or {}
    total = 0.0
    for i, mid in enumerate(MID):
        try:
            total += float(probs.get(str(i), 0.0)) * mid
        except Exception:  # noqa: BLE001
            pass
    if total == 0.0 and ans.get("score") is not None:
        try:
            total = MID[max(0, min(4, int(round(float(ans["score"])))))]
        except Exception:  # noqa: BLE001
            total = 0.0
    return total


def main():
    if not decision_client.enabled():
        print("STARTLUX_API_KEY not set")
        return 1
    import time
    score_q = {k: QUESTIONS[k] for k in WEIGHTS}
    meta_q = {k: QUESTIONS[k] for k in ("top30", "pilot", "award")}
    out = None
    for i in range(4):
        try:
            out = decision_client.decide(STATE, score_q, think_mode="auto", gate=0.9, timeout=90)
            break
        except Exception as e:
            print("[judge] 重试", i + 1, repr(e)[:80], flush=True)
            time.sleep(3)
    if not out:
        print("startlux unavailable"); return 1
    ans = dict(out.get("answers") or {})
    for i in range(3):
        try:
            meta = decision_client.decide(STATE, meta_q, think_mode="auto", gate=0.9, timeout=90)
            ans.update(meta.get("answers") or {})
            break
        except Exception as e:
            print("[judge] meta 重试", i + 1, repr(e)[:80], flush=True)
            time.sleep(3)

    rows, total = [], 0.0
    for k, w in WEIGHTS.items():
        a = ans.get(k) or {}
        pts = _expected(a)
        total += pts * w
        rows.append((NAMES[k], w, round(pts, 1), a.get("probabilities") or {}))

    top30 = float((ans.get("top30") or {}).get("noul") or 0.0)
    pilot = float((ans.get("pilot") or {}).get("noul") or 0.0)
    award = ans.get("award") or {}
    award_probs = award.get("probabilities") or {}
    best_award = max(award_probs, key=lambda x: award_probs[x]) if award_probs else "-"

    lines = ["# 评委打分模拟（StartLux，非官方）", "",
             f"- 模型：{out.get('model')} ｜ think_mode=auto",
             f"- 加权总分：**{total:.1f} / 100**", "",
             "| 维度 | 权重 | 分数 |", "|---|---:|---:|"]
    for name, w, pts, _ in rows:
        lines.append(f"| {name} | {int(w*100)}% | {pts} |")
    lines += ["", "## 晋级与奖项", "",
              f"- 进前 30 概率：**{top30:.3f}**",
              f"- 90 天 pilot 概率：**{pilot:.3f}**",
              f"- 最可能奖项：**{best_award}**",
              "", "| 奖项 | 概率 |", "|---|---:|"]
    for k, v in sorted(award_probs.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", "> 说明：这是决策模型按给定证据做的等级判断，不是评委；用它找短板，不要对外宣称分数。"]

    os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
    p = os.path.join(ROOT, "report", "judge_sim.md")
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("->", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
