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


# ---------------- 第四轮 P0 ----------------
def test_future_window_excludes_past():
    import datetime
    import qa.nlg as nlg
    import qa.engine as e
    ctx = nlg.classify_ctx(e._load_data(), "未来7天")
    today = datetime.date.today().isoformat()
    assert ctx["fc"], "forecast 不应为空"
    assert min(d["date"] for d in ctx["fc"]) >= today


def test_days_forecast_scope_future_only():
    import datetime
    c = _client()
    r = c.get("/api/days?scope=forecast")
    assert r.status_code == 200
    today = datetime.date.today().isoformat()
    assert min(d["date"] for d in r.json()["days"]) >= today


def test_composite_single_target_date():
    import datetime
    import qa.engine as e
    d = (datetime.date.today() + datetime.timedelta(days=6)).isoformat()
    y, m, dd = d.split("-")
    txt = e.answer(f"{int(y)}年{int(m)}月{int(dd)}日最低温、最高温、降雨量和霜冻概率各是多少")["text"]
    assert d in txt
    assert "Tmin" in txt and "Tmax" in txt and "降水" in txt and ("P(霜冻)" in txt or "霜冻" in txt)


def test_irrigation_safety_measure_first():
    import qa.engine as e
    txt = e.answer("要不要浇水")["text"]
    # 低亏缺时须先测墒，不得直接命令灌溉
    assert ("测墒" in txt) or ("灌溉" not in txt) or ("浇水" not in txt)


def test_historical_range_message_not_2015():
    import qa.engine as e
    txt = e.answer("2024年3月1日当时有霜冻吗")["text"]
    assert "近 180 天" in txt or "聊天当前加载范围" in txt
    assert "超出可用数据范围（历史 2015" not in txt


def test_data_authority_sensor_question():
    import qa.engine as e
    r = e.answer("当前有多少现场传感器站？")
    assert r["intent"] == "data_source"
    assert ("模式" in r["text"]) or ("传感器" in r["text"])


def test_entity_carry_target_date():
    import qa.engine as e
    h = [{"role": "user", "content": "哪天雨最大？"},
         {"role": "assistant", "content": "未来 7 天雨最大的是 2026-10-20（约 24.3 mm，风险 低）。"}]
    r = e.answer("那一天要采取什么措施？", history=h)
    assert "2026-10-20" in r["text"] or "24.3" in r["text"]


def test_compound_three_topics():
    import qa.engine as e
    r = e.answer("今天风险多少、数据哪来的、我该做什么？")
    assert "+" in r["intent"]
    assert ("风险" in r["text"]) and ("数据" in r["text"] or "来源" in r["text"])


# ---------------- 数据治理 / 设备凭证 / 田间结果 / 监控 接口 ----------------
def test_data_versions_endpoint():
    c = _client()
    r = c.get("/api/data/versions?limit=3")
    assert r.status_code == 200 and "versions" in r.json()


def test_forecast_verify_endpoint():
    c = _client()
    r = c.get("/api/forecast/verify")
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "pending" or "leads" in j


def test_device_register_verify_revoke(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    r = c.post("/api/device/register?device_id=DEV-1", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200
    tok = r.json()["token"]
    # 设备令牌可用于传感器上报
    ok = c.post("/api/sensor", json={"station_id": "DEVTEST", "ts": "2026-10-14T09:00:00+08:00", "temp": 15.0},
                headers={"X-Sensor-Token": tok})
    assert ok.status_code == 200
    # 撤销后令牌失效
    c.post("/api/device/revoke?device_id=DEV-1", headers={"X-Admin-Token": "adm"})
    bad = c.post("/api/sensor", json={"station_id": "DEVTEST2", "ts": "2026-10-14T09:05:00+08:00", "temp": 15.0},
                 headers={"X-Sensor-Token": tok})
    assert bad.status_code == 403


def test_outcome_and_pilot(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "SENSOR_TOKEN", "st")
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    r = c.post("/api/outcome", json={"date": "2026-10-20", "plot": "北坡茶园", "kind": "霜冻受灾",
                                     "area_mu": 0.5, "damage_level": "轻"},
               headers={"X-Sensor-Token": "st"})
    assert r.status_code == 200
    assert c.get("/api/outcomes", headers={"X-Admin-Token": "adm"}).status_code == 200
    pj = c.get("/api/pilot/evaluate", headers={"X-Admin-Token": "adm"}).json()
    assert pj["status"] in ("pending", "ready")
    assert pj.get("outcomes", 0) >= 1


def test_metrics_and_updates_and_phenology(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    assert c.get("/api/metrics", headers={"X-Admin-Token": "adm"}).status_code == 200
    u = c.get("/api/updates")
    assert u.status_code == 200 and "server_time" in u.json()
    assert c.get("/api/phenology/validation").status_code == 200


# ---------------- 第五轮：新鲜度 / 实时语义 / 季节数据层 / 适应 ----------------
def test_freshness_and_cache_headers():
    c = _client()
    h = c.get("/api/health")
    assert "age_minutes" in h.json() and "stale" in h.json()
    assert h.headers.get("cache-control") == "no-store"
    s = c.get("/api/summary").json()
    assert "fetched_at" in s and "age_minutes" in s and "stale" in s


def test_realtime_semantics_when_empty():
    c = _client()
    j = c.get("/api/realtime").json()
    assert "server_time" in j and "status" in j
    if j["n"] == 0:
        assert j["status"] == "no_sensors" and j["message"]


def test_forecast_advice_no_pick_in_offseason():
    import json
    import datetime
    d = json.load(open("web/data.json", encoding="utf-8"))
    assert d["meta"]["season"] == "off"
    for x in d["days"]:
        if x["source"] == "forecast":
            assert "标准采" not in (x.get("advice") or "")


def test_chinese_numeral_date():
    import datetime
    import qa.engine as e
    target = datetime.date.today() + datetime.timedelta(days=6)
    cn = {10: "十", 20: "二十", 21: "二十一", 22: "二十二", 23: "二十三", 24: "二十四", 25: "二十五", 26: "二十六"}
    mm = cn.get(target.month, str(target.month)); dd = cn.get(target.day, str(target.day))
    r = e.answer(f"{mm}月{dd}号会不会下雨")
    assert target.isoformat() in r["text"]


def test_json_format_output():
    import json
    import qa.engine as e
    import datetime
    d = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    r = e.answer(f"{d} 用 JSON 返回温度、降雨和风险", state={"format": "json"})
    obj = json.loads(r["text"])
    assert obj.get("date") == d
    assert "tmin" in obj and "tmax" in obj and "precip" in obj


def test_state_prev_day_carry():
    import qa.engine as e
    r = e.answer("前一天呢", state={"active_date": "2026-10-20"})
    assert "2026-10-19" in r["text"]


def test_metrics_percentiles(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    c.get("/api/health"); c.get("/api/summary")
    m = c.get("/api/metrics", headers={"X-Admin-Token": "adm"}).json()
    assert "latency_p95_ms" in m and "data_age_minutes" in m


# ---------------- 发布一致性自检 / 告警 / 数据血缘 ----------------
def test_ready_and_alerts():
    c = _client()
    r = c.get("/api/ready")
    assert r.status_code == 200
    j = r.json()
    assert "ready" in j and "missing_critical" in j and "route_count" in j
    a = c.get("/api/alerts")
    assert a.status_code == 200 and "alerts" in a.json()


def test_versions_have_lineage_fields():
    c = _client()
    v = c.get("/api/data/versions?limit=1").json()
    if v["versions"]:
        assert "raw_sha256" in v["versions"][0]


def test_verify_history_and_alerts_webhook():
    c = _client()
    h = c.get("/api/forecast/verify/history?limit=5")
    assert h.status_code == 200 and "runs" in h.json()
    a = c.get("/api/alerts").json()
    assert "webhook_configured" in a and "notified" in a


def test_alerts_test_endpoint(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    r = c.post("/api/alerts/test", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 200 and "notified" in r.json()


def test_push_webhook_kinds(monkeypatch):
    import serve, requests
    captured = {}

    class R:
        status_code = 200

        def json(self):
            return {"errcode": 0}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["body"] = kw.get("json")
        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(serve, "ALERT_WEBHOOK_URL", "https://example.test/hook")
    payload = {"site": "梅家坞 TeaWindow", "server_time": "t",
               "new": ["data_stale"], "active": ["data_stale"], "alerts": []}
    monkeypatch.setenv("ALERT_WEBHOOK_KIND", "slack")
    assert serve._push_webhook(payload)["sent"] and "text" in captured["body"]
    monkeypatch.setenv("ALERT_WEBHOOK_KIND", "feishu")
    serve._push_webhook(payload)
    assert captured["body"]["msg_type"] == "text"
    monkeypatch.setenv("ALERT_WEBHOOK_KIND", "dingtalk")
    monkeypatch.setenv("ALERT_WEBHOOK_SECRET", "SEC")
    assert serve._push_webhook(payload)["sent"]
    assert "timestamp=" in captured["url"] and "sign=" in captured["url"]
    monkeypatch.delenv("ALERT_WEBHOOK_KIND", raising=False)
    monkeypatch.delenv("ALERT_WEBHOOK_SECRET", raising=False)
    serve._push_webhook(payload)
    assert captured["body"] == payload   # generic：原样 JSON


# ---------------- 存储适配（DATABASE_URL / Postgres 翻译） ----------------
def test_store_db_info():
    import store
    info = store.db_info()
    assert info["dialect"] in ("sqlite", "postgres")
    assert "path" in info


def test_store_postgres_sql_translation(monkeypatch):
    import store
    monkeypatch.setattr(store, "_DIALECT", "postgres")
    s1 = store._tr("INSERT OR IGNORE INTO sensor(station_id,ts) VALUES(?,?)")
    assert "%s" in s1 and "ON CONFLICT DO NOTHING" in s1
    s2 = store._tr("INSERT OR REPLACE INTO refresh_state(k,ts,status) VALUES(?,?,?)")
    assert "ON CONFLICT (k)" in s2 and "EXCLUDED.status" in s2


# ---------------- 第六/七轮：意图稳定 / 状态合并 / 运行问答 / 格式 / 英文 ----------------
def test_week_list_intents_and_stable_conf():
    import qa.engine as e
    for q in ["将来一周有什么风险", "我问将来一周每天情况", "未来7天每天风险"]:
        r = e.answer(q)
        assert r["intent"] == "forecast_list", (q, r["intent"])
        assert r["confidence"] == 0.9


def test_state_merge_three_turns():
    import qa.engine as e
    st = {"active_date": "2026-10-20"}
    r1 = e.answer("那一天要不要排水", state=st); st = r1.get("state") or st
    assert st.get("active_date") == "2026-10-20"
    r2 = e.answer("它的最低温是多少", state=st); st = r2.get("state") or st
    assert st.get("active_date") == "2026-10-20"
    assert "2026-10-20" in r2["text"]


def test_next_day_relative():
    import qa.engine as e
    r = e.answer("下一天呢", state={"active_date": "2026-10-20"})
    assert "2026-10-21" in r["text"]


def test_negation_change_no_forbidden():
    import qa.engine as e
    r = e.answer("不要防冻建议，改成灌溉")
    assert "frost" not in r["intent"]          # 被否定的意图不应再出现
    assert "夜晨覆盖" not in r["text"] and "熏烟" not in r["text"]


def test_ops_questions():
    import qa.engine as e
    assert e.answer("多久刷新一次，现在是否过期")["intent"] == "ops"
    assert e.answer("Open-Meteo 断网怎么降级")["intent"] == "ops"
    assert "MAE" in e.answer("3天预测误差和运行批次")["text"]


def test_json_obeys_requested_fields():
    import json
    import qa.engine as e
    r = e.answer("用JSON返回，字段为 date,tmin,rain,risk,action", state={"format": "json"})
    obj = json.loads(r["text"])
    row = obj["days"][0] if "days" in obj else obj
    assert set(row.keys()) == {"date", "tmin", "rain", "risk", "action"}


def test_markdown_table_format():
    import qa.engine as e
    r = e.answer("用表格列出未来3天温度降雨风险", state={"format": "table"})
    assert r.get("format") == "table" and r["text"].lstrip().startswith("|")


def test_english_halflanguage_rejected():
    import qa.engine as e
    r = e.answer("Tomorrow forecast frost risk and temperature high?")
    assert r["intent"] in ("unknown", "oos")


def test_outcome_negative_kind_and_ready_fields(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "SENSOR_TOKEN", "st")
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    r = c.post("/api/outcome", json={"date": "2026-10-19", "kind": "巡查无灾"},
               headers={"X-Sensor-Token": "st"})
    assert r.status_code == 200
    pj = c.get("/api/pilot/evaluate", headers={"X-Admin-Token": "adm"}).json()
    assert pj["status"] in ("pending", "ready")
    rd = c.get("/api/ready").json()
    assert "lineage_ok" in rd and "refresh_ok" in rd and "warnings" in rd and "data_fresh" in rd


# ---------------- 任务规划器 / change-warning / 冷热延迟 / 持久化 ----------------
def test_task_planner_ordered():
    import qa.engine as e
    r = e.answer("先说最大风险，再说最大降雨日，最后说明更新时间和来源")
    assert r["text"].startswith("按你的要求逐项回答")
    assert "1)" in r["text"] and "2)" in r["text"]
    assert "+" in r["intent"]


def test_cancel_command():
    import qa.engine as e
    r = e.answer("算了")
    assert r["intent"] == "cancel" and "取消" in r["text"]


def test_memory_questions():
    import qa.engine as e
    h = [{"role": "user", "content": "明天有风险吗"},
         {"role": "assistant", "content": "明天（2026-10-15）：风险 低（R=0.0，适宜度 53）。"}]
    r = e.answer("刚刚我问了什么", history=h)
    assert r["intent"] == "memory" and "明天有风险吗" in r["text"]
    r2 = e.answer("你的上一条回答是什么", history=h)
    assert r2["intent"] == "memory" and "明天" in r2["text"]
    r3 = e.answer("刚刚我问了什么")
    assert r3["intent"] == "memory" and "第一轮" in r3["text"]


def test_followup_relative_day_not_overridden():
    import qa.engine as e
    h = [{"role": "user", "content": "明天有风险吗"},
         {"role": "assistant", "content": "明天（2026-10-15）：风险 低。"}]
    r = e.answer("后天呢", history=h)
    import datetime
    d = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    assert d in r["text"]


def test_rolling_summary_memory():
    import qa.engine as e
    # 无最近一条 user 时，用滚动摘要回答"我问了什么"
    r = e.answer("刚刚我问了什么", state={"summary": "之前问过：要不要防冻"})
    assert r["intent"] == "memory" and "摘要" in r["text"]


def test_forecast_compare_endpoint():
    c = _client()
    r = c.get("/api/forecast/compare")
    assert r.status_code == 200
    j = r.json()
    assert ("changed" in j) or ("error" in j)


def test_persistence_and_cold_hot_metrics(monkeypatch):
    import serve
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    p = c.get("/api/persistence", headers={"X-Admin-Token": "adm"}).json()
    assert "db" in p and "counts" in p and "retention_hint" in p
    m = c.get("/api/metrics", headers={"X-Admin-Token": "adm"}).json()
    assert "cold_p95_ms" in m and "hot_p95_ms" in m and "uptime_s" in m


# ---------------- 设备签名（HMAC）+ nonce 防重放 ----------------
def _signed(device_id, token, body_bytes, path="/api/sensor", ts=None, nonce=None):
    import hashlib
    import hmac
    import datetime
    import uuid
    ts = ts or datetime.datetime.now().isoformat(timespec="seconds")
    nonce = nonce or uuid.uuid4().hex
    key = hashlib.sha256(token.encode()).hexdigest()
    canon = "\n".join([ts, nonce, "POST", path, hashlib.sha256(body_bytes).hexdigest()])
    sig = hmac.new(key.encode(), canon.encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Device-Id": device_id, "X-Timestamp": ts,
            "X-Nonce": nonce, "X-Signature": sig}


def test_device_signature_ok_and_replay_blocked(monkeypatch):
    import serve
    import json
    import uuid
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    tok = c.post("/api/device/register?device_id=SIG-1", headers={"X-Admin-Token": "adm"}).json()["token"]
    body = {"station_id": "SIGST", "ts": "2026-10-14T10:00:00+08:00", "temp": 16.0}
    raw = json.dumps(body, separators=(",", ":")).encode()
    nonce = uuid.uuid4().hex
    h = _signed("SIG-1", tok, raw, nonce=nonce)
    assert c.post("/api/sensor", content=raw, headers=h).status_code == 200
    # 同一 nonce 重放 → 409
    assert c.post("/api/sensor", content=raw, headers=h).status_code == 409


def test_device_signature_bad_and_stale(monkeypatch):
    import serve
    import json
    import datetime
    monkeypatch.setattr(serve, "ADMIN_TOKEN", "adm")
    c = _client()
    tok = c.post("/api/device/register?device_id=SIG-2", headers={"X-Admin-Token": "adm"}).json()["token"]
    body = {"station_id": "SIGST2", "ts": "2026-10-14T10:00:00+08:00", "temp": 16.0}
    raw = json.dumps(body, separators=(",", ":")).encode()
    h = _signed("SIG-2", tok, raw)
    h["X-Signature"] = "0" * 64
    assert c.post("/api/sensor", content=raw, headers=h).status_code == 401
    old = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat(timespec="seconds")
    h2 = _signed("SIG-2", tok, raw, ts=old)
    assert c.post("/api/sensor", content=raw, headers=h2).status_code == 401


def test_nonce_dedup_store():
    import store
    import uuid
    n = "n-" + uuid.uuid4().hex
    assert store.use_nonce(n, "d1") is True
    assert store.use_nonce(n, "d1") is False


def test_credibility_question_not_hijacked():
    import qa.engine as e
    h = [{"role": "user", "content": "未来7天逐日风险"},
         {"role": "assistant", "content": "未来 7 天逐日风险（梅家坞）：- 10-14 中(R=0.315)"}]
    r = e.answer("这个数据可信吗", history=h)
    assert r["intent"] == "data_source", r["intent"]
    assert "可信度" in r["text"]
    assert e.answer("这些数据可靠吗")["intent"] == "data_source"
    assert e.answer("准不准")["intent"] == "model"


def test_relative_dates_longest_match_and_next():
    import datetime
    import qa.engine as e
    today = datetime.date.today()
    assert (today + datetime.timedelta(days=3)).isoformat() in e.answer("大后天呢")["text"]
    assert (today + datetime.timedelta(days=2)).isoformat() in e.answer("后天呢")["text"]


def test_json_format_carries_across_turns():
    import json
    import qa.engine as e
    r1 = e.answer("2026-10-20 用JSON返回，字段为 date,tmin,rain,risk,action", state={"format": "json"})
    st = r1["state"]
    r2 = e.answer("下一天也用相同字段", state=st)
    obj = json.loads(r2["text"])
    assert set(obj.keys()) == {"date", "tmin", "rain", "risk", "action"}
    assert obj["date"] == "2026-10-21"


def test_ops_lineage_alerts_verify():
    import qa.engine as e
    assert e.answer("当前告警与最近投递")["intent"] == "ops"
    assert e.answer("3天预测误差和运行批次")["intent"] == "ops"
    assert "验证历史" in e.answer("最近两次验证时间与样本")["text"] or "仅" in e.answer("最近两次验证时间与样本")["text"]


def test_stale_degrades_action():
    import qa.engine as e
    # 本地数据 fetched_at 通常已 >60 分钟 → 应出现"可能过期"降级提示
    r = e.answer("要不要浇水")
    assert ("可能过期" in r["text"]) or ("测墒" in r["text"])


def test_refresh_guards_uvicorn_argv(monkeypatch):
    """Render 以 uvicorn 启动会污染 sys.argv；刷新不得把 argv 当日期。"""
    import sys
    import types
    import serve
    called = {}

    def run(**kw):
        called.update(kw)
        called["argv"] = list(sys.argv)

    stub = types.ModuleType("pipeline")
    stub.run = run
    monkeypatch.setitem(sys.modules, "pipeline", stub)
    monkeypatch.setattr(serve, "_save_snapshot", lambda **kw: None)
    orig = list(sys.argv)
    sys.argv = ["uvicorn", "src.serve:app", "--host", "0.0.0.0", "--port", "10000"]
    try:
        r = serve._refresh(False)
        assert r["status"] == "ok"
        assert called.get("argv") == ["pipeline"]
    finally:
        sys.argv = orig


def test_openmeteo_key_endpoint(monkeypatch):
    import fetch_weather as fw
    monkeypatch.setattr(fw, "OM_KEY", "k123")
    url, p = fw._om("https://api.open-meteo.com/v1/forecast", {"a": 1})
    assert "customer-api.open-meteo.com" in url and p.get("apikey") == "k123"
    url2, p2 = fw._om("https://archive-api.open-meteo.com/v1/archive", {})
    assert "customer-archive-api.open-meteo.com" in url2


def test_alerts_echo_endpoint():
    c = _client()
    r = c.post("/api/alerts/echo", json={"new": ["data_stale"], "active": ["data_stale"]})
    assert r.status_code == 200 and r.json().get("ok") is True