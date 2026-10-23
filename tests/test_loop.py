"""有界闭环（生成→校验→修复→再校验）的离线测试。"""
from qa import loop


def _v(decision, sup=0.9, act=0.9, safe=0.9, note=""):
    return {"decision": decision, "scores": {"supported": sup, "actionable": act, "safe": safe}, "note": note}


def test_revise_adds_only_failing_items():
    ans, notes = loop.revise("结论：低风险。", _v("annotate", sup=0.2, act=0.9, safe=0.9))
    assert len(notes) == 1 and "证据不足" in notes[0]
    assert "结论：低风险。" in ans and "证据不足" in ans

    ans2, notes2 = loop.revise("结论", _v("ok"))
    assert notes2 == [] and ans2 == "结论"


def test_loop_repairs_then_passes(monkeypatch):
    seq = iter([_v("annotate", sup=0.3, act=0.8, safe=0.9, note="需复核"), _v("ok")])
    monkeypatch.setattr(loop.gate, "review", lambda *a, **k: next(seq))
    out = loop.run("q", "原始答案", "evidence", max_rounds=2)
    assert out["rounds"] == 2
    assert out["verdict"]["decision"] == "ok"
    assert "证据不足" in out["answer"]
    assert len(out["trace"]) == 2


def test_loop_stops_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(loop.gate, "review", lambda *a, **k: None)
    out = loop.run("q", "a", "e", max_rounds=2)
    assert out["verdict"] is None and out["answer"] == "a"


def test_loop_single_round_no_repair(monkeypatch):
    monkeypatch.setattr(loop.gate, "review", lambda *a, **k: _v("review", sup=0.3))
    out = loop.run("q", "a", "e", max_rounds=1)
    assert out["rounds"] == 1 and out["answer"] == "a"
    assert out["verdict"]["decision"] == "review"
