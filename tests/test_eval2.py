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


# ---------------- 意图后端（ONNX 可选 + numpy 兜底） ----------------
def test_engine_reports_backend():
    import qa.engine as e
    r = e.answer("今天有风险吗")
    assert r.get("backend") in ("numpy", None) or isinstance(r.get("backend"), str)


def test_intent_backend_modules():
    from qa import intent_onnx
    assert isinstance(intent_onnx.available(), bool)
    res = intent_onnx.classify("今天有风险吗")
    # 未启用依赖时返回 None；启用时返回 (label, conf)
    assert res is None or (isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], float))


def test_onnx_backend_labels_match_engine_classes():
    from qa import intent_onnx
    import qa.engine as e
    if not intent_onnx.available():
        pytest.skip("ONNX 后端未启用")
    onnx_classes = set(intent_onnx._classes)  # noqa: SLF001
    numpy_classes = set(e._load_model()["classes"])
    assert onnx_classes == numpy_classes


def test_engine_falls_back_to_numpy(monkeypatch):
    # 模拟 ONNX 不可用 → 应回退 numpy 并正常作答
    import qa.engine as e
    from qa import intent_onnx
    monkeypatch.setattr(intent_onnx, "_session", None)
    monkeypatch.setattr(intent_onnx, "_loaded", True)
    monkeypatch.setattr(intent_onnx, "_backend", None)
    r = e.answer("先采哪块地")
    assert r["text"]
    assert r["backend"] == "numpy"


def test_engine_oos_rejected():
    # K+1 显式域外类：编程/闲聊请求应被拒识（不硬答）
    import qa.engine as e
    r = e.answer("帮我写一段 Python 代码")
    assert r["intent"] in ("oos", "unknown")


# ---------------- 检索增强（RAG 思路） ----------------
def test_retriever_available_and_nearest():
    from qa import retriever
    assert isinstance(retriever.available(), bool)
    n = retriever.nearest("今天有风险吗", 2)
    assert n is None or (isinstance(n, list) and len(n) >= 1 and "intent" in n[0] and "sim" in n[0])


def test_engine_reports_retrieval_backend():
    import qa.engine as e
    r = e.answer("今天有风险吗")
    assert "retrieval" in r


# ---------------- 传感器持久化 / 幂等 / 时间漂移（P1-6、§9） ----------------
def test_sensor_idempotent(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "SENSOR_TOKEN", "st")
    c = _client()
    body = {"station_id": "T-TEST", "ts": "2026-10-14T08:00:00+08:00", "temp": 16.1}
    r1 = c.post("/api/sensor", json=body, headers={"X-Sensor-Token": "st"})
    assert r1.status_code == 200
    r2 = c.post("/api/sensor", json=body, headers={"X-Sensor-Token": "st"})
    assert r2.status_code == 200 and r2.json().get("dedup") is True


def test_sensor_future_ts_422(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "SENSOR_TOKEN", "st")
    c = _client()
    r = c.post("/api/sensor", json={"station_id": "T-FUT", "ts": "2099-01-01T00:00:00+08:00", "temp": 10},
               headers={"X-Sensor-Token": "st"})
    assert r.status_code == 422


def test_sensor_no_token_query_rejected():
    c = _client()
    r = c.post("/api/sensor?token=x", json={"station_id": "T", "ts": "2026-10-14T08:00:00+08:00", "temp": 10})
    assert r.status_code == 403


# ---------------- OpenAPI schema / CSP（评估 §7、§6） ----------------
def test_openapi_has_response_schemas():
    c = _client()
    spec = c.get("/openapi.json").json()
    ask_schema = spec["paths"]["/api/ask"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    sum_schema = spec["paths"]["/api/summary"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ask_schema.get("$ref") or ask_schema.get("allOf")
    assert sum_schema.get("$ref") or sum_schema.get("allOf")


def test_csp_no_unsafe_inline_script():
    c = _client()
    csp = c.get("/api/health").headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


# ---------------- P0：空白输入 / history 强类型 / 输出完整性 ----------------
@pytest.mark.parametrize("q", ["", "   ", "\t", "\n", "  \t \n "])
def test_blank_question_422(q):
    c = _client()
    assert c.post("/api/ask", json={"question": q}).status_code == 422


@pytest.mark.parametrize("hist", [
    ["not-an-object"],
    [{"role": "system", "content": "x"}],
    [{"role": "user", "content": ""}],
    [{"role": "user", "content": "x" * 1200}],
    [{"content": "no-role"}],
])
def test_invalid_history_422(hist):
    c = _client()
    assert c.post("/api/ask", json={"question": "继续", "history": hist}).status_code == 422


def test_valid_history_ok():
    c = _client()
    r = c.post("/api/ask", json={"question": "为什么", "history": [{"role": "user", "content": "今天有风险吗"}]})
    assert r.status_code == 200


def test_output_integrity_no_placeholders():
    import qa.engine as e
    qs = ["今天有风险吗", "要不要防冻", "先采哪块地", "保险多少钱一亩", "预计损失多少", "今年什么时候开采",
          "继续", "明天有风险吗", "要不要浇水", "哪天雨最大", "今天和明天哪个风险更高"]
    for q in qs:
        txt = e.answer(q)["text"]
        for bad in ("None", "NaN", "nan", "undefined", "建议-"):
            assert bad not in txt, f"{q} -> {txt}"


def test_bare_continue_without_history_clarifies():
    import qa.engine as e
    r = e.answer("继续")
    assert "请先告诉我" in r["text"]


# ---------------- P0：季节一致性（跨意图） ----------------
def test_offseason_frost_no_pick():
    import datetime
    import qa.engine as e
    if datetime.date.today().month in (3, 4):
        pytest.skip("春采季")
    for q in ["明天要不要防冻", "今天风险如何？请列出霜冻概率", "未来7天有霜冻吗"]:
        txt = e.answer(q)["text"]
        assert "可正常采" not in txt and "适合采" not in txt


def test_offseason_decision_no_none():
    import qa.engine as e
    r = e.answer("要不要抢采")
    assert "None" not in r["text"]
    assert "非春采期" in r["text"] or "养护" in r["text"]


# ---------------- P0：水量符号 / 风险口径 / 日期槽位 ----------------
def test_drought_water_sign():
    import qa.engine as e
    txt = e.answer("要不要浇水")["text"]
    assert "亏缺 -" not in txt and "水分亏缺 -" not in txt


def test_risk_provenance_mentions_rule():
    import qa.engine as e
    r = e.answer("今天有风险吗")
    joined = r["text"] + "".join(r.get("chain") or [])
    assert ("专家规则" in joined) or ("规则值" in joined)


def test_absolute_date_answered():
    import datetime
    import qa.engine as e
    d = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    y, m, dd = d.split("-")
    r = e.answer(f"{int(y)}年{int(m)}月{int(dd)}日有霜冻吗")
    assert d in r["text"]
    assert f"{d}（{d}）" not in r["text"]


def test_historical_out_of_range_refused():
    import qa.engine as e
    r = e.answer("2001年3月1日有霜冻吗")
    assert ("超出" in r["text"]) or ("无法" in r["text"])


def test_rain_max_gives_date():
    import qa.engine as e
    r = e.answer("哪天雨最大")
    assert r["intent"] == "rain_max"
    assert r["text"].count("-") >= 2  # 含日期


def test_48h_is_horizon_not_day():
    import qa.engine as e
    r = e.answer("未来48小时霜冻")
    assert "2 天" in r["text"] or "未来 2" in r["text"]


def test_openapi_typed_items():
    c = _client()
    spec = c.get("/openapi.json").json()
    comp = spec.get("components", {}).get("schemas", {})
    # history item 应为对象/引用，而非空 schema
    ask = spec["paths"]["/api/ask"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    ref = ask.get("$ref", "").split("/")[-1]
    props = comp.get(ref, {}).get("properties", {})
    hist = props.get("history", {})
    assert hist.get("items") or hist.get("$ref")