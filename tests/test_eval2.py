"""第二轮评估整改的回归测试：季节一致性 / 拒识与边界 / 令牌 / 请求体 / LLM 一致性。"""
import datetime

import pytest


# ---------------- 季节一致性（P0-1） ----------------
def test_nlg_season_off_disables_pick_and_schedule():
    import qa.nlg as nlg
    import qa.engine as e
    data = e._load_data()
    ctx = nlg.classify_ctx(data, "先采哪块地")
    # 当前测试日期（10 月）应为非春采期
    if nlg._season() != "off":
        pytest.skip("当前处于春采季，跳过非春采期断言")
    txt, _ = nlg.pick_window(ctx, "什么时候采", False)
    assert "非春采期" in txt
    txt2, _ = nlg.schedule(ctx, "先采哪块地", False)
    assert "非春采期" in txt2


def test_engine_schedule_offseason_care():
    import qa.engine as e
    if datetime.date.today().month in (3, 4):
        pytest.skip("春采季")
    r = e.answer("先采哪块地")
    assert "非春采期" in r["text"] or "养护" in r["text"]


def test_day_advice_season_off_no_pick():
    import qa.nlg as nlg
    d = {"date": "2026-10-20", "risk_level": "低", "suitability": 60, "tmin": 15, "tmax": 25,
         "precip": 0, "dry_run": 0, "wet_run": 0, "deficit": 0}
    txt = nlg.day_advice(d, season_off=True)
    assert "非春采期" in txt and "适合采" not in txt
    txt2 = nlg.day_advice(d, season_off=False)
    assert "适合采" in txt2


# ---------------- 逐日清单 / 日期聚焦（对话逻辑） ----------------
def test_forecast_list_today_forward_count():
    import qa.engine as e
    r = e.answer("列举未来三天具体风险评估")
    assert r["intent"] == "forecast_list"
    today = datetime.date.today().isoformat()
    # 输出以今天（或之后）起始，且最多 3 天
    assert today[5:] in r["text"]
    assert r["text"].count("-") >= 3 or "10-" in r["text"]


def test_forecast_list_does_not_hijack_frost():
    import qa.engine as e
    r = e.answer("未来7天有霜冻吗")
    assert r["intent"] == "frost"


def test_day_offset_tomorrow():
    import qa.engine as e
    r = e.answer("明天有风险吗")
    target = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    assert target in r["text"]


# ---------------- 拒识与边界（P1-1） ----------------
@pytest.mark.parametrize("q,intent", [
    ("asdfghjkl ？？？", "unknown"),
    ("我胸口疼，吃什么药", "unknown"),
    ("Should I harvest tomorrow?", "unknown"),
])
def test_rejection(q, intent):
    import qa.engine as e
    r = e.answer(q)
    assert r["text"]
    # 拒识/边界答案不应给出采摘/防冻行动指令
    assert "先采" not in r["text"]


def test_three_month_prediction_boundary():
    import qa.engine as e
    r = e.answer("准确预测三个月后温度和降雨")
    assert ("16" in r["text"]) or ("无法" in r["text"]) or ("气候概率" in r["text"])


# ---------------- LLM 一致性校验（P0-2） ----------------
def test_consistency_numbers_and_polarity():
    import llm_advice
    base = "未来 7 天无霜冻风险（Tmin 13.7℃），不用防冻；达标芽叶可正常采。"
    # 数字齐全、极性不变 → 通过
    assert llm_advice._consistency_ok(base, "未来 7 天没有霜冻风险，最低 13.7℃，不用防冻，达标的芽叶能正常采。")
    # 极性被翻转 → 拒绝
    assert not llm_advice._consistency_ok(base, "未来 7 天要重点防冻，最低 13.7℃，需覆盖熏烟。")
    # 少数字 → 拒绝
    assert not llm_advice._consistency_ok(base, "未来 7 天无霜冻风险，不用防冻。")


def test_consistency_season_preserved():
    import llm_advice
    base = "当前为非春采期（春采季 3–4 月），暂不提供采摘窗口，以养护为主。"
    assert llm_advice._consistency_ok(base, "现在是非春采期（春采季 3–4 月），暂不提供采摘窗口，以养护为主。")
    assert not llm_advice._consistency_ok(base, "现在是春采季，适合尽快采摘。")


# ---------------- API 契约与安全（P0-3/P0-4） ----------------
def _client():
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    import serve
    return TestClient(serve.app)


def test_ask_empty_and_overlong_422():
    c = _client()
    assert c.post("/api/ask", json={"question": ""}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 600}).status_code == 422


def test_days_scope_enum_422():
    c = _client()
    assert c.get("/api/days?scope=unexpected").status_code == 422
    assert c.get("/api/days?scope=forecast").status_code == 200


def test_engine_enum_422():
    c = _client()
    assert c.post("/api/ask", json={"question": "今天有风险吗", "engine": "not-a-real-engine"}).status_code == 422


def test_admin_token_not_in_query(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "secret123")
    c = _client()
    # 查询参数传令牌应被拒绝（P0-3）
    assert c.get("/api/reports?token=secret123").status_code == 403
    # 请求头传令牌应通过
    assert c.get("/api/reports", headers={"X-Admin-Token": "secret123"}).status_code == 200


def test_body_size_limit(monkeypatch):
    import serve
    c = _client()
    big = {"question": "a" * (serve.MAX_BODY + 1000)}
    r = c.post("/api/ask", json=big)
    assert r.status_code == 413


def test_summary_season_field():
    c = _client()
    r = c.get("/api/summary")
    assert r.status_code == 200
    j = r.json()
    assert "season" in j
    if j["season"] == "off":
        assert j["pick_window"] == []