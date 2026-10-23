"""有界闭环：生成 → 校验 → 修复 → 再校验（最多 N 轮）。

设计约束（避免"模型自嗨"）：
- 修复动作是**确定性的、可枚举的**（加提示/给保守动作/加免责声明），不让模型重写结论；
- 最多 2 轮，任何一轮失败即停（fail-open）；
- 每轮 verdict 都进 trace，可在 /qa_review 复核；
- 规则仍是主结论，闭环只提升"可交付质量"，不替换决策。
"""
import os

from qa import gate

REPAIR = {
    "supported": "⚠️ 证据不足：当前数值/日期未被数据快照直接支持。请先看「验证与证据」页，或换一种问法。",
    "actionable": "建议先按「观察 / 常规管护」执行；需要具体动作可以问“未来 3 天怎么管”。",
    "safe": "提示：以上为决策辅助，请结合田间实勘与官方预警后再行动。",
}


def revise(answer, verdict):
    """根据失败项追加确定性修复文案。返回 (新答案, 修复项列表)。"""
    s = (verdict or {}).get("scores") or {}
    notes = []
    if s.get("supported") is not None and s["supported"] < 0.45:
        notes.append(REPAIR["supported"])
    if s.get("actionable") is not None and s["actionable"] < 0.35:
        notes.append(REPAIR["actionable"])
    if s.get("safe") is not None and s["safe"] < 0.35:
        notes.append(REPAIR["safe"])
    if not notes:
        return answer, []
    return (answer or "").rstrip() + "\n\n" + "\n".join(notes), notes


def run(question, answer, evidence, max_rounds=2, timeout=None):
    """返回 {answer, verdict, trace, rounds}。未配置/失败时 verdict=None。"""
    rounds = max(1, min(int(max_rounds), 3))
    trace, cur = [], answer
    for i in range(rounds):
        v = gate.review(question, cur, evidence, timeout=timeout)
        if not v:
            return {"answer": cur, "verdict": None, "trace": trace, "rounds": i}
        trace.append({"round": i + 1, "decision": v.get("decision"),
                      "scores": v.get("scores"), "note": v.get("note")})
        if v.get("decision") == "ok":
            return {"answer": cur, "verdict": v, "trace": trace, "rounds": i + 1}
        # 只有"证据不足"才进入修复；"review" 只提示、不再多花一轮
        if v.get("decision") != "annotate":
            return {"answer": cur, "verdict": v, "trace": trace, "rounds": i + 1}
        if i == rounds - 1:
            break
        cur2, fixes = revise(cur, v)
        if not fixes:
            break
        cur = cur2
    return {"answer": cur, "verdict": trace and gate_rebuild(trace[-1]), "trace": trace, "rounds": len(trace)}


def gate_rebuild(last):
    """把 trace 的最后一项还原成 verdict 形状（decision/scores/note）。"""
    return {"decision": last.get("decision"), "scores": last.get("scores") or {}, "note": last.get("note") or ""}
