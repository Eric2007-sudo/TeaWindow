"""离线反馈聚类的离线测试。"""
from qa import feedback


def _row(intent, sup=None, act=None, safe=None, data=None, decision="ok"):
    scores = {}
    if sup is not None:
        scores["supported"] = sup
    if act is not None:
        scores["actionable"] = act
    if safe is not None:
        scores["safe"] = safe
    gate = {"decision": decision, "scores": scores}
    if data:
        gate["data"] = {"verdict": data}
    return {"intent": intent, "question": "q-" + intent, "answer": "a", "gate": gate}


def test_build_clusters_failures():
    rows = [
        _row("frost", sup=0.2),
        _row("frost", sup=0.3, act=0.2),
        _row("risk_today", sup=0.9, act=0.9, safe=0.9),
        {"intent": "x", "question": "q", "answer": "a", "gate": None},
    ]
    r = feedback.build(rows)
    assert r["total"] == 4 and r["gated"] == 3
    top = {(c["intent"], c["dim"]): c["count"] for c in r["clusters"]}
    assert top[("frost", "supported")] == 2
    assert top[("frost", "actionable")] == 1


def test_data_dimension_flagged():
    r = feedback.build([_row("ops", sup=0.9, act=0.9, safe=0.9, data="unreliable")])
    assert any(c["dim"] == "data" for c in r["clusters"])


def test_render_contains_baseline_and_labels_note():
    md = feedback.render(feedback.build([_row("frost", sup=0.1)]),
                         {"ml": {"auc": 0.99, "f1": 0.85}, "test_years": "2024-2026-10-10"})
    assert "失败聚类" in md and "0.99" in md
    assert "不把 StartLux 的判定当训练标签" in md
