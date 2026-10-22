"""1+5 护栏：StartLux 放行 + 事实核对的离线测试（不联网）。"""
from qa import gate


def _fake(ans):
    def _try(state, questions, **kw):
        return {"model": "fake", "answers": ans}
    return _try


def test_high_scores_pass(monkeypatch):
    monkeypatch.setattr(gate.decision_client, "try_decide", _fake({
        "supported": {"type": "noul", "noul": 0.95},
        "actionable": {"type": "noul", "noul": 0.9},
        "safe": {"type": "noul", "noul": 0.93},
        "usability": {"type": "score", "score": 1.8, "confidence": 0.8},
    }))
    v = gate.review("今天有风险吗", "低风险，按常规管护。", "2026-10-21 Tmin=12.4 R=0.0 低")
    assert v["decision"] == "ok"
    assert v["note"] == ""
    assert v["scores"]["supported"] == 0.95


def test_low_support_annotates(monkeypatch):
    monkeypatch.setattr(gate.decision_client, "try_decide", _fake({
        "supported": {"type": "noul", "noul": 0.2},
        "actionable": {"type": "noul", "noul": 0.8},
        "safe": {"type": "noul", "noul": 0.8},
        "usability": {"type": "score", "score": 0.4},
    }))
    v = gate.review("q", "a", "evidence")
    assert v["decision"] == "annotate"
    assert "一致性偏低" in v["note"]


def test_mid_scores_request_review(monkeypatch):
    monkeypatch.setattr(gate.decision_client, "try_decide", _fake({
        "supported": {"type": "noul", "noul": 0.75},
        "actionable": {"type": "noul", "noul": 0.3},
        "safe": {"type": "noul", "noul": 0.8},
    }))
    v = gate.review("q", "a", "evidence")
    assert v["decision"] == "review"
    assert "实勘" in v["note"]


def test_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(gate.decision_client, "try_decide", lambda *a, **k: None)
    assert gate.review("q", "a", "e") is None
