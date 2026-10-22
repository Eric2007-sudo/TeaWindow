"""1+5：自研系统生成 → StartLux 放行 → 事实核对（RAG 护栏）。

职责边界：
- 生成：项目自研（规则 + GBDT + 模板），保证数值、日期、行动都来自数据；
- 放行（gate）：StartLux 判断「合规 / 可执行 / 不越界」；
- 事实核对（grounding）：StartLux 判断「答案里的关键数值与日期是否被证据支持」。

失败策略：fail-open。未配置 key、超时、返回异常时一律放行，只记录，不阻断用户。
任何情况下都不让外部模型覆盖安全结论——它只能加提示或标记「需复核」。
"""
import os

import decision_client

QUESTIONS = {
    "supported": {
        "type": "noul",
        "instructions": "答案中的关键数值与日期，是否都能被 evidence 直接支持？不要凭常识补全，找不到依据就答否。",
    },
    "actionable": {
        "type": "noul",
        "instructions": "答案是否给出了明确、可执行的下一步（采 / 防冻 / 灌溉 / 观察 / 排水）？",
    },
    "safe": {
        "type": "noul",
        "instructions": "答案是否避免绝对化承诺，并保留人工实勘与官方预警的最终决定权？",
    },
    "usability": {
        "type": "score",
        "instructions": "这条回答对茶农今天的可用程度如何？",
        "criteria": ["不可用", "需复核", "可直接用"],
    },
}

ANNOTATE_LOW_SUPPORT = (
    "⚠️ 自动核对：这条回答与当前数据证据的一致性偏低。"
    "请先看「验证与证据」页或换一种问法，再决定是否行动。"
)
ANNOTATE_REVIEW = "ℹ️ 自动核对：置信度一般，建议结合田间实勘与官方预警后再行动。"


def _p(ans, key):
    try:
        return float((ans.get(key) or {}).get("noul") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def review(question, answer, evidence, timeout=None):
    """返回 {decision, scores, note, model} 或 None（未配置/失败）。"""
    state = {
        "question": question or "",
        "answer": answer or "",
        "evidence": evidence or "(无可用证据)",
    }
    t = timeout or float(os.environ.get("STARTLUX_GATE_TIMEOUT", "6"))
    out = decision_client.try_decide(state, QUESTIONS, think_mode="auto", gate=0.9, timeout=t)
    if not out:
        return None

    ans = out.get("answers") or {}
    sup, act, safe = _p(ans, "supported"), _p(ans, "actionable"), _p(ans, "safe")
    try:
        usab = float((ans.get("usability") or {}).get("score"))
    except Exception:  # noqa: BLE001
        usab = None

    decision, note = "ok", ""
    if sup < 0.5 or safe < 0.4:
        decision, note = "annotate", ANNOTATE_LOW_SUPPORT
    elif min(sup, act, safe) < 0.7:
        decision, note = "review", ANNOTATE_REVIEW

    return {
        "decision": decision,
        "scores": {"supported": round(sup, 3), "actionable": round(act, 3),
                   "safe": round(safe, 3), "usability": usab},
        "note": note,
        "model": out.get("model") or decision_client.model_id(),
    }
