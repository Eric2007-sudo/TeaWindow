"""自研问答引擎单元测试。"""


def test_engine_answer_fields():
    import qa.engine as e
    r = e.answer("今天有风险吗")
    assert r["engine"] == "teawindow-own"
    assert isinstance(r["text"], str) and len(r["text"]) > 5
    assert "intent" in r and "confidence" in r


def test_intent_classes_loaded():
    import qa.engine as e
    m = e._load_model()
    assert len(m["classes"]) >= 10


def test_keyword_fallback_frost():
    import qa.engine as e
    r = e.answer("要不要防冻")
    assert r["intent"] == "frost"


def test_model_question_mentions_self():
    import qa.engine as e
    r = e.answer("你们用什么模型")
    assert "自研" in r["text"] or "GBDT" in r["text"]
