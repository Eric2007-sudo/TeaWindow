"""StartLux 决策客户端的离线测试（不联网、不需要 key）。"""
import decision_client as dc


def _clear(monkeypatch):
    for k in ("STARTLUX_API_KEY", "BAMBOO_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_disabled_by_default(monkeypatch):
    _clear(monkeypatch)
    assert dc.enabled() is False
    q = {"a": {"type": "noul", "instructions": "?"}}
    assert dc.try_decide("state", q) is None


def test_decide_parses_response(monkeypatch):
    monkeypatch.setenv("STARTLUX_API_KEY", "test-key")

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"model": "m", "answers": {"a": {"type": "choice",
                                                    "probabilities": {"x": 0.8, "y": 0.2}}},
                    "usage": {"input_tokens": 1, "output_tokens": 1}}

    seen = {}

    def fake_post(url, **kw):
        seen["url"] = url
        seen["json"] = kw.get("json")
        seen["headers"] = kw.get("headers")
        return R()

    monkeypatch.setattr(dc.requests, "post", fake_post)
    out = dc.decide("茶园状态", {"a": {"type": "choice", "instructions": "选", "criteria": {"x": "", "y": ""}}})
    assert out["answers"]["a"]["type"] == "choice"
    assert seen["url"].endswith("/decisions")
    assert seen["json"]["model"] == dc.model_id()
    assert seen["headers"]["Authorization"].startswith("Bearer ")


def test_decide_rejects_bad_questions(monkeypatch):
    monkeypatch.setenv("STARTLUX_API_KEY", "k")
    for bad in ({}, None, "x"):
        try:
            dc.decide("s", bad)  # type: ignore[arg-type]
            raise AssertionError("should raise")
        except ValueError:
            pass


def test_best_choice_noul_score():
    label, conf, _ = dc.best({"a": {"type": "choice", "probabilities": {"采": 0.7, "防": 0.3}}}, "a")
    assert label == "采" and abs(conf - 0.7) < 1e-9

    label, conf, _ = dc.best({"b": {"type": "noul", "noul": 0.82}}, "b")
    assert label == "yes" and abs(conf - 0.82) < 1e-9

    label, conf, _ = dc.best({"c": {"type": "score", "score": 1.4, "confidence": 0.6}}, "c")
    assert abs(label - 1.4) < 1e-9 and abs(conf - 0.6) < 1e-9

    assert dc.best({}, "missing")[0] is None
