"""预测辅助（霜型/一致性/置信度）的离线测试。"""
from qa import predict_assist as pa


def _fake(ans):
    def _try(state, questions, **kw):
        assert "tmin" in state
        return {"model": "fake", "answers": ans}
    return _try


def test_assess_maps_answers(monkeypatch):
    monkeypatch.setattr(pa.decision_client, "try_decide", _fake({
        "frost_type": {"type": "choice", "probabilities": {"辐射霜": 0.8, "平流霜": 0.1, "无霜冻": 0.1}},
        "confidence": {"type": "score", "score": 1.7, "confidence": 0.8},
        "consistent": {"type": "noul", "noul": 0.9},
    }))
    v = pa.assess({"date": "2026-10-27", "tmin": 2.4, "tmax": 15.0, "risk_R": 0.4, "wind": 3.0, "rh": 80})
    assert v["frost_type"] == "辐射霜"
    assert v["confidence_label"] == "高"
    assert v["consistent"] == 0.9
    assert "辐射霜型" in v["note"]


def test_assess_low_confidence_notes(monkeypatch):
    monkeypatch.setattr(pa.decision_client, "try_decide", _fake({
        "frost_type": {"type": "choice", "probabilities": {"平流霜": 0.5, "无霜冻": 0.4, "辐射霜": 0.1}},
        "confidence": {"type": "score", "score": 0.3},
        "consistent": {"type": "noul", "noul": 0.2},
    }))
    v = pa.assess({"date": "2026-10-27", "tmin": 5.0})
    assert v["confidence_label"] == "低"
    assert "复核" in v["note"] or "分歧" in v["note"]


def test_assess_returns_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(pa.decision_client, "try_decide", lambda *a, **k: None)
    assert pa.assess({"date": "2026-10-27"}) is None
