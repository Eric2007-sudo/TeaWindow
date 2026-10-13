"""
A-3 自研问答引擎（纯 numpy，离线可跑）。
流程：意图分类(我们训练的模型) → 槽位抽取 → 读取我们项目的数据/模型 → 接地生成答案 + 来源链。
设计说明：答案来自**本项目数据与模型**（GBDT复合风险/GDD物候/指数保险/调度/决策），
不依赖外部大模型；DeepSeek 仅在显式 engine=llm 时作为可选增强。
"""
import json
import os
import re
import datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(ROOT, "models")
WEB = os.path.join(ROOT, "web")
QA = os.path.join(ROOT, "data", "qa")

_model = None
_data = None
_kg = None


def _load_model():
    global _model
    if _model is None:
        with open(os.path.join(MODELS, "qa_intent.json"), encoding="utf-8") as f:
            m = json.load(f)
        m["W"] = np.array(m["W"], dtype="float32")
        m["b"] = np.array(m["b"], dtype="float32")
        _model = m
    return _model


def _load_data():
    global _data
    p = os.path.join(WEB, "data.json")
    if _data is None or _data.get("_mtime") != os.path.getmtime(p):
        with open(p, encoding="utf-8") as f:
            _data = json.load(f)
        _data["_mtime"] = os.path.getmtime(p)
    return _data


def _load_kg():
    global _kg
    if _kg is None:
        with open(os.path.join(QA, "knowledge.json"), encoding="utf-8") as f:
            _kg = json.load(f)
    return _kg


def _grams(text):
    t = "".join(ch for ch in text if ch.strip())
    return list(t) + [t[i:i + 2] for i in range(len(t) - 1)]


def _vec(text, vocab):
    D = len(vocab)
    x = np.zeros(D, dtype="float32")
    for g in _grams(text):
        j = vocab.get(g)
        if j is not None:
            x[j] += 1.0
    s = x.sum()
    if s > 0:
        x /= s
    return x


KEYWORDS = {
    "insurance": ["保险", "保费", "理赔", "赔付", "保额"],
    "value": ["值多少", "损失", "亏", "省多少"],
    "frost": ["霜冻", "倒春寒", "下霜", "打霜", "冻"],
    "heat": ["高温", "热", "晒", "灼", "遮阳"],
    "drought": ["干旱", "缺水", "灌溉", "浇水", "墒"],
    "rain": ["下雨", "连阴雨", "排水", "涝", "湿"],
    "schedule": ["采哪", "先采", "排班", "安排", "顺序"],
    "pick_window": ["什么时候采", "采摘", "开采", "明前", "雨前", "窗口"],
    "decision": ["抢采", "还是等", "等两天", "冒险"],
    "harvest_date": ["开采期", "什么时候开采", "几号", "上市"],
    "data_source": ["数据", "来源", "卫星", "遥感", "台站"],
    "model": ["模型", "AI", "准确", "训练", "大模型", "预测"],
    "plot": ["哪块地", "地块", "坡", "海拔", "地形"],
    "risk_today": ["风险", "今天", "现在", "预警"],
    "greet": ["你好", "谢谢", "在吗", "早上好"],
}


def _keyword_intent(q):
    for it, kws in KEYWORDS.items():
        if any(k in q for k in kws):
            return it
    return None


# 强关键词（无歧义）优先于分类器
STRONG = [
    ("寒潮", "frost"), ("冷空气", "frost"), ("霜冻", "frost"), ("倒春寒", "frost"), ("防冻", "frost"), ("降温", "frost"),
    ("高温", "heat"), ("遮阳", "heat"), ("热害", "heat"), ("灼伤", "heat"),
    ("干旱", "drought"), ("灌溉", "drought"), ("浇水", "drought"), ("墒", "drought"),
    ("连阴雨", "rain"), ("排水", "rain"), ("防涝", "rain"),
    ("保险", "insurance"), ("保费", "insurance"), ("理赔", "insurance"), ("赔付", "insurance"),
    ("开采期", "harvest_date"), ("开采日", "harvest_date"), ("什么时候开采", "harvest_date"), ("上市", "harvest_date"),
    ("先采", "schedule"), ("采哪", "schedule"), ("排班", "schedule"), ("安排采", "schedule"),
    ("抢采", "decision"),
    ("数据来源", "data_source"), ("从哪来", "data_source"), ("用什么模型", "model"), ("准确率", "model"),
    ("哪块地", "plot"), ("地块", "plot"),
    # 逐日清单（放末尾，灾害类词优先命中）
    ("列举", "forecast_list"), ("列出", "forecast_list"), ("逐日", "forecast_list"),
    ("每天的", "forecast_list"), ("逐天", "forecast_list"),
    ("未来一周", "forecast_list"), ("未来7天", "forecast_list"), ("未来七天", "forecast_list"),
    ("未来3天", "forecast_list"), ("未来三天", "forecast_list"), ("未来5天", "forecast_list"),
    ("未来五天", "forecast_list"), ("未来十天", "forecast_list"), ("未来几天", "forecast_list"),
]


def _strong_intent(q):
    for k, it in STRONG:
        if k in q:
            return it
    return None


def _horizon(q):
    if "一个月" in q or "30天" in q or "1个月" in q:
        return 30
    if "半个月" in q or "15天" in q:
        return 15
    if "两周" in q or "14天" in q:
        return 14
    if "一周" in q or "7天" in q:
        return 7
    m = re.search(r"(\d+)\s*天", q)
    return int(m.group(1)) if m else None


def classify(q):
    # 优先使用 GPU 蒸馏的 ONNX 意图模型（可用时），否则回退本地 numpy 模型
    try:
        from . import intent_onnx
    except Exception:  # noqa: BLE001
        intent_onnx = None
    if intent_onnx is not None:
        r = intent_onnx.classify(q)
        if r is not None:
            return r
    m = _load_model()
    x = _vec(q, m["vocab"])
    z = m["W"] @ x + m["b"]
    p = np.exp(z - z.max()); p /= p.sum()
    i = int(p.argmax())
    return m["classes"][i], float(p[i])


def intent_backend():
    try:
        from . import intent_onnx
        return intent_onnx.backend() or "numpy"
    except Exception:  # noqa: BLE001
        return "numpy"


def _slots(q, data):
    plots = [p["name"] for p in (data.get("terrain", {}) or {}).get("plots", [])]
    plot = next((p for p in plots if p in q), None)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})?\s*[日号]?", q)
    date = f"{m.group(1)}月{m.group(2)+'日' if m.group(2) else ''}" if m else None
    return {"plot": plot, "date": date}


def _fmt(lst):
    return "；".join(lst)


def _frost_answer(q, data):
    fc = [d for d in data["days"] if d["source"] == "forecast"]
    H = _horizon(q) or 7
    sub = fc[:min(H, len(fc))]
    pfmax = max((d.get("p_frost") or 0) for d in sub) if sub else 0
    frost_days = [d["date"] for d in sub if d.get("frost") or (d.get("p_frost") or 0) > 0.2]
    today = datetime.date.today()
    months = sorted({(today + datetime.timedelta(days=k)).month for k in range(H + 1)})
    clim = data.get("climatology", {}).get("monthly", [])
    probs = [c["frost_day_prob"] for c in clim if c["month"] in months]
    clim_prob = max(probs) if probs else 0
    end = (today + datetime.timedelta(days=H)).isoformat()
    text = f"未来 {H} 天（至 {end}）寒潮/霜冻展望：预报期霜冻概率最高 P={pfmax:.2f}，"
    text += ("有霜冻风险日：" + "、".join(frost_days) + "。") if frost_days else "无霜冻风险日。"
    if H > 16:
        text += (f" 超出 16 天无逐日预报，参考历史气候：{'、'.join(str(m) for m in months)} 月"
                 f"出现霜冻日的概率约 {clim_prob*100:.0f}%——"
                 + ("需开始关注防冻。" if clim_prob > 0.2 else "总体偏低，可暂不重点防冻。"))
    text += " 建议：达标芽叶优先抢采；夜晨低温可覆盖/熏烟/喷水防御。"
    return text


def _horizon_label(H):
    return f"{H}天" if H else "近7天"


def compose(intent, q, sl, data):
    days = data["days"]
    fc = [d for d in days if d["source"] == "forecast"]
    hist = [d for d in days if d["source"] == "history"]
    cur = hist[-1]
    n7 = fc[:7]
    mx = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else cur
    chains = []
    # P0-1：季节策略在业务层统一——非春采期不产出采摘类建议
    season = (data.get("meta", {}) or {}).get("season") or \
        ("spring" if datetime.date.today().month in (3, 4) else "off")
    if season == "off" and intent in ("pick_window", "decision", "schedule"):
        return {"text": "当前为非春采期（西湖龙井 43 春采季为 3–4 月），本工具此时以园间养护为主："
                        "关注防霜冻/干旱/连阴雨，规划修剪、施肥、清沟与越冬管理，暂不提供采摘窗口与排班。",
                "chains": ["季节约束: 非春采期"]}
    if intent == "greet":
        return {"text": "你好！我是梅坞采候助手，可以问：今天风险、要不要防冻/灌溉、采哪块地、保险与损失等。", "chains": ["自研问答引擎"]}
    if intent in ("risk_today", "plot"):
        risk = f"最近研判日 {cur['date']} 风险 {cur['risk_level']}（R={cur['risk_R']}），适宜度 {cur['suitability']}；未来7天最高在 {mx['date']}（{mx['risk_level']}）。"
        if intent == "plot":
            plots = (data.get("terrain", {}) or {}).get("plots", [])
            pr = [(p["name"], p["frost_risk"]) for p in plots]
            risk += " 地块霜冻易感：" + "、".join(f"{n}({r})" for n, r in pr) + "。北坡/低洼更需防霜。"
            chains.append("模型: 地形霜冻易感")
        chains += ["数据: Open-Meteo", "模型: GBDT复合风险"]
        return {"text": risk, "chains": chains}
    if intent == "frost":
        return {"text": _frost_answer(q, data),
                "chains": ["数据: Open-Meteo 16天预报 + 逐月气候概率", "模型: 霜冻/倒春寒 + 集合 P(霜冻)"]}
    if intent == "heat":
        hs = [d for d in n7 if d.get("heat") or (d.get("p_heat") or 0) > 0.2]
        text = "未来7天无明显高温胁迫。" if not hs else ("未来7天高温风险日：" + "、".join(d["date"] for d in hs) + "。")
        text += " 建议：高温日上遮阳网、傍晚浇透水、避免正午修剪。"
        return {"text": text, "chains": ["数据: Open-Meteo+集合预报", "模型: 高温/干旱复合"]}
    if intent == "drought":
        text = f"当前连续少雨 {cur.get('dry_run', 0)} 天，水分亏缺 {cur.get('deficit', 'NA')}；土壤偏干。建议每4–5天灌一次并稻草覆盖保墒，早晚浇透、忌中午猛灌。"
        return {"text": text, "chains": ["数据: Open-Meteo", "模型: 干旱(水分亏缺)"]}
    if intent == "rain":
        text = f"近况连阴雨日数 {cur.get('wet_run', 0)}。连阴雨鲜叶含水高，注意及时摊青防闷堆；低洼茶园清沟排水防沤根。"
        return {"text": text, "chains": ["数据: Open-Meteo", "模型: 连阴雨指标"]}
    if intent in ("pick_window", "decision"):
        dec = data.get("decision", {})
        best = dec.get("best_pick_day", "-")
        today = dec["days"][0] if dec.get("days") else None
        text = f"推荐最佳采摘日：{best}。"
        if today:
            text += f" 今日建议：{today['recommend']}（抢采EV {today['ev_pick']} / 防护EV {today['ev_protect']} / 等待EV {today['ev_wait']}）。"
        wins = data.get("pick_window", [])
        if wins:
            text += " 未来适宜度前3：" + "、".join(f"{w['date']}({w['suitability']})" for w in wins[:3]) + "。"
        return {"text": text, "chains": ["模型: 采摘适宜度 + 决策论期望效用"]}
    if intent == "schedule":
        sch = (data.get("schedule", {}) or {}).get("schedule", [])
        lines = ["、".join(p["name"] for p in s["plots"]) + f"（{s['date']}）" for s in sch]
        text = "采摘排班建议：" + "；".join(lines) + "（按每日产能与地块霜冻易感排序）。"
        return {"text": text, "chains": ["模型: 采摘调度优化"]}
    if intent == "insurance":
        ins = data.get("insurance", {})
        text = (f"可参考天气指数保险：霜冻阈值 {ins.get('frost_threshold')} 度日、"
                f"赔付 {ins.get('payout_frost')} 元/亩；历史赔付年 {ins.get('fire_years')}/{ins.get('n_years')}，"
                f"精算公平保费≈{ins.get('fair_premium_per_mu')} 元/亩。不依赖人工查勘、按客观指数自动理赔。")
        return {"text": text, "chains": ["模型: 天气指数保险(客观指数)"]}
    if intent == "value":
        v = data.get("value", {})
        text = (f"按示意测算：亩产值约 {v.get('value_per_mu')} 元，期望损失≈{v.get('expected_loss_per_mu')} 元/亩·年，"
                f"参考保费 {v.get('premium_per_mu')} 元/亩，工具减损价值≈{v.get('tool_benefit_per_mu')} 元/亩·年。")
        return {"text": text, "chains": ["模型: 价值闭环"]}
    if intent == "harvest_date":
        ph = data.get("phenology", {})
        if ph:
            text = f"今年（以 GDD {ph.get('threshold')}℃·d 预测）开采日约 {ph.get('predicted_date')}；历史对官方开采日 MAE≈{ph.get('mae')} 天。"
        else:
            text = "开采期由有效积温(GDD)预测；近年官方开采日多在 3月13–20日。"
        return {"text": text, "chains": ["模型: GDD 物候", "真值: 官方开采日"]}
    if intent == "data_source":
        kg = _load_kg()
        return {"text": "数据来源：" + _fmt(kg["data_sources"]) + "。", "chains": ["本项目数据管线"]}
    if intent == "model":
        kg = _load_kg()
        return {"text": "本问答由自研流程驱动：" + _fmt(kg["model"] + kg["qa_engine"]) + "。", "chains": ["自研模型与数据流"]}
    # 兜底
    return {"text": f"我可以帮你看风险、防冻/灌溉、采摘窗口、采哪块地、保险与损失等。当前：{cur['date']} 风险 {cur['risk_level']}，推荐采摘日 {data.get('decision',{}).get('best_pick_day','-')}。",
            "chains": ["自研问答引擎"]}


OFFTOPIC = ["药", "疼", "病", "感冒", "头疼", "股票", "基金", "彩票", "贷款", "汇率"]


def _reply(text, intent="unknown", chain=None):
    return {"engine": "teawindow-own", "mode": "rules", "intent": intent, "confidence": 0.0,
            "backend": intent_backend(), "slots": {}, "detail": False, "follow_up": False, "text": text,
            "chain": chain or ["自研问答引擎"]}


def answer(question, context=None, history=None):
    data = _load_data()
    q0 = (question or "").strip()
    if not q0:
        return _reply("请描述你的问题，例如：今天有风险吗、要不要防冻、先采哪块地、保险多少钱一亩。")
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in q0)
    if not has_cjk and any(c.isalpha() for c in q0):
        return _reply("This assistant currently supports Chinese only. 请用中文提问，例如：今天有风险吗？")
    if any(w in q0 for w in OFFTOPIC):
        return _reply("抱歉，我只服务梅家坞茶园的气候风险与采摘决策（如：风险、防冻、灌溉、采摘、保险、开采期）。"
                      "健康/金融等非农业问题请咨询专业人员。")
    if (("温度" in q0 or "气温" in q0 or "降雨" in q0 or "降水" in q0)
            and ("个月" in q0 or "季度" in q0 or "半年" in q0 or "一年" in q0)):
        return _reply("我们只能给出 16 天逐日预报与逐月气候概率（历史统计），"
                      "无法准确预测三个月后的逐日气温/降雨；更远的趋势请参考气候概率或官方季节预测。")
    # 多轮上下文：识别"追问"并继承上一话题/时效
    prev = ""
    if history:
        for m in reversed(history):
            if m.get("role") == "user":
                prev = m.get("content", "") or ""
                break
    follow_marks = ["呢", "那", "这个", "它", "详细", "展开", "为什么", "依据", "具体", "原因"]
    is_follow = (len(question) <= 12) and any(t in question for t in follow_marks) and not _strong_intent(question)
    qt = (question + " " + prev) if (is_follow and prev) else question

    intent, conf = classify(qt)
    strong = _strong_intent(question) or _strong_intent(qt)
    kw = _keyword_intent(qt)
    if strong:
        intent, conf = strong, max(conf, 0.9)
    elif conf < 0.8 and kw:
        intent, conf = kw, max(conf, 0.8)
    # K+1 显式域外类：无强关键词命中时，直接拒答/给边界
    if not strong and not kw and intent == "oos":
        return _reply("这个问题超出我的能力范围：我只服务梅家坞茶园的气候风险与采摘/养护决策"
                      "（风险、防冻、灌溉、采摘窗口、保险、开采期等）。其他问题请咨询相应专业人员。",
                      intent="oos", chain=["拒识: 域外(K+1 分类)"])
    if not strong and not kw and conf < 0.45:
        return _reply("我不太确定你的问题。可以这样问：今天有风险吗 / 要不要防冻 / 先采哪块地 / 保险多少钱 / 今年什么时候开采。")
    sl = _slots(qt, data)
    try:
        from . import nlg
    except Exception:  # noqa: BLE001
        import nlg  # type: ignore
    res = nlg.compose(intent, qt, sl, data)
    return {"engine": "teawindow-own", "mode": "rules", "intent": intent, "confidence": round(conf, 2),
            "backend": intent_backend(),
            "slots": sl, "detail": bool(res.get("detail")), "follow_up": bool(is_follow),
            "text": res["text"], "chain": res["chain"]}


if __name__ == "__main__":
    for q in ["今天有风险吗", "要不要防冻", "先采哪块地", "保险多少钱", "今年什么时候开采", "你们用什么模型"]:
        r = answer(q)
        print(f"[{r['intent']} {r['confidence']}] {q}\n  -> {r['text']}\n")
