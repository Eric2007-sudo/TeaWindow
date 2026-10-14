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

import season

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
    "ops": ["刷新", "多久更新", "多久刷新", "过期", "数据年龄", "降级", "断网", "提前期", "运行批次", "血缘", "更新时间"],
    "plot": ["哪块地", "地块", "坡", "海拔", "地形"],
    "risk_today": ["风险", "今天", "现在", "预警"],
    "greet": ["你好", "谢谢", "在吗", "早上好"],
}


def _keyword_intent(q):
    for it, kws in KEYWORDS.items():
        if any(k in q for k in kws):
            return it
    return None


# 表达适应：繁简/常见错字/中英术语归一
_NORM = {"未來": "未来", "兩天": "两天", "兩周": "两周", "兩天": "两天", "採摘": "采摘", "採": "采",
         "澆": "浇", "嗎": "吗", "會": "会", "週": "周", "號": "号", "天氣": "天气", "氣溫": "气温",
         "霜凍": "霜冻", "風險": "风险", "預報": "预报", "灌溉": "灌溉",
         "明夭": "明天", "今夭": "今天", "霜栋": "霜冻",
         "risk": "风险", "frost": "霜冻", "rain": "降雨", "temperature": "气温", "weather": "天气",
         "irrigation": "灌溉", "harvest": "采摘", "drought": "干旱", "heat": "高温", "insurance": "保险"}


def _normalize(q):
    q = q or ""
    for k, v in _NORM.items():
        q = q.replace(k, v)
    return q


STRONG = [
    ("寒潮", "frost"), ("冷空气", "frost"), ("霜冻", "frost"), ("倒春寒", "frost"), ("防冻", "frost"), ("降温", "frost"),
    ("受冻", "frost"), ("冻蔫", "frost"), ("冻坏", "frost"), ("冻掉", "frost"), ("冻伤", "frost"),
    ("打霜", "frost"), ("下霜", "frost"), ("低温", "frost"), ("结冰", "frost"),
    ("高温", "heat"), ("遮阳", "heat"), ("热害", "heat"), ("灼伤", "heat"),
    ("晒焦", "heat"), ("焦边", "heat"), ("焦掉", "heat"), ("日头毒", "heat"), ("太阳毒", "heat"), ("晒伤", "heat"),
    ("干旱", "drought"), ("灌溉", "drought"), ("浇水", "drought"), ("墒", "drought"),
    ("灌水", "drought"), ("抽水", "drought"), ("缺水", "drought"), ("干裂", "drought"),
    ("连阴雨", "rain"), ("排水", "rain"), ("防涝", "rain"), ("降雨", "rain"), ("雨水", "rain"),
    ("摊晾", "rain"), ("青叶", "rain"),
    ("保险", "insurance"), ("保费", "insurance"), ("理赔", "insurance"), ("赔付", "insurance"),
    ("开采期", "harvest_date"), ("开采日", "harvest_date"), ("什么时候开采", "harvest_date"), ("上市", "harvest_date"),
    ("发芽", "harvest_date"), ("抽芽", "harvest_date"), ("出芽", "harvest_date"), ("早发", "harvest_date"), ("开摘", "harvest_date"),
    ("先采", "schedule"), ("采哪", "schedule"), ("排班", "schedule"), ("安排采", "schedule"),
    ("抢采", "decision"),
    ("气象台", "data_source"),
    # 最大雨日 / 对比（优先于逐日清单）
    ("雨最大", "rain_max"), ("最大雨", "rain_max"), ("哪天雨", "rain_max"), ("降雨最大", "rain_max"),
    ("哪个风险", "compare"), ("哪个更高", "compare"), ("哪个高", "compare"), ("风险更高", "compare"),
    ("数据来源", "data_source"), ("从哪来", "data_source"), ("用什么模型", "model"), ("准确率", "model"),
    ("刷新", "ops"), ("多久更新", "ops"), ("多久刷新", "ops"), ("过期", "ops"), ("数据年龄", "ops"),
    ("降级", "ops"), ("断网", "ops"), ("提前期", "ops"), ("运行批次", "ops"), ("血缘", "ops"), ("更新时间", "ops"),
    ("误差", "ops"), ("准不准", "model"), ("可信", "data_source"), ("可靠", "data_source"), ("靠谱", "data_source"),
    ("造假", "data_source"), ("数据", "data_source"),
    ("告警", "ops"), ("通知", "ops"), ("送达", "ops"), ("投递", "ops"), ("最近两次", "ops"), ("两次", "ops"),
    ("样本", "ops"), ("验证历史", "ops"), ("差异", "ops"), ("漂移", "ops"), ("信谁", "ops"), ("上游", "ops"),
    ("传感器", "data_source"), ("台站", "data_source"), ("实时站", "data_source"), ("现场站", "data_source"),
    ("受灾", "data_source"), ("产量", "data_source"), ("盲测", "data_source"), ("误报", "model"), ("漏报", "model"),
    ("哪块地", "plot"), ("地块", "plot"),
    # 逐日清单（放末尾，灾害类词优先命中）
    ("列举", "forecast_list"), ("列出", "forecast_list"), ("逐日", "forecast_list"),
    ("每天的", "forecast_list"), ("每天", "forecast_list"), ("每日", "forecast_list"),
    ("逐天", "forecast_list"), ("将来", "forecast_list"), ("一周", "forecast_list"),
    ("这周", "forecast_list"), ("本周", "forecast_list"),
    ("未来一周", "forecast_list"), ("未来7天", "forecast_list"), ("未来七天", "forecast_list"),
    ("未来3天", "forecast_list"), ("未来三天", "forecast_list"), ("未来5天", "forecast_list"),
    ("未来五天", "forecast_list"), ("未来十天", "forecast_list"), ("未来几天", "forecast_list"),
    ("48小时", "forecast_list"), ("48 小时", "forecast_list"),
]


# 否定/改口：删除被否定的关键词，避免"不要回答霜冻，我想问雨"仍命中霜冻
_NEG_RE = re.compile(r"(?:不要|别|不再|不是|不)(?:回答|问|关心|看|问)?\s*"
                     r"(霜冻|倒春寒|高温|干旱|灌溉|浇水|保险|采摘|排班|风险|连阴雨|降雨|雨水|防冻|遮阳|排水)")


_NEG_MARK = ["改问", "改成", "换问", "不是问", "不要回答", "别回答", "别问", "算了", "不问", "不是要"]


def _strip_negations(q):
    # 仅当出现"改口/否定"标记时才删除被否定关键词，避免误伤"要不要防冻"这类普通问句
    if not any(m in (q or "") for m in _NEG_MARK):
        return q
    return _NEG_RE.sub("", q)


def _strong_intent(q):
    for k, it in STRONG:
        if k in q:
            return it
    return None


def _strong_all(q):
    """按优先级返回命中的强意图（去重，保序），用于复合问题拆解。"""
    out = []
    for k, it in STRONG:
        if k in q and it not in out:
            out.append(it)
    return out


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


RETR_ADOPT = 0.95     # 检索近邻相似度阈值（BGE 短句余弦普遍偏高，取保守值）


def _retrieval_nearest(q, k=3):
    try:
        from . import retriever
    except Exception:  # noqa: BLE001
        return None
    if not retriever.available():
        return None
    return retriever.nearest(q, k)


def retrieval_backend():
    try:
        from . import retriever
        return retriever.backend()
    except Exception:  # noqa: BLE001
        return None


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
            "backend": intent_backend(), "retrieval": retrieval_backend(),
            "slots": {}, "detail": False, "follow_up": False, "text": text,
            "chain": chain or ["自研问答引擎"]}


_COMPOUND_CUES = [
    ("风险", "risk_today"), ("数据", "data_source"), ("来源", "data_source"), ("哪来", "data_source"),
    ("模型", "model"), ("准确", "model"), ("误报", "model"), ("漏报", "model"),
    ("保险", "insurance"), ("保费", "insurance"), ("损失", "value"), ("值多少", "value"),
    ("开采", "harvest_date"), ("防冻", "frost"), ("霜冻", "frost"), ("高温", "heat"),
    ("干旱", "drought"), ("浇水", "drought"), ("灌溉", "drought"), ("降雨", "rain"), ("排水", "rain"),
    ("该做什么", "decision"), ("做什么", "decision"), ("措施", "decision"), ("怎么办", "decision"), ("建议", "decision"),
    ("最大降雨", "rain_max"), ("雨最大", "rain_max"), ("最大风险", "risk_today"),
    ("更新时间", "ops"), ("刷新", "ops"),
]


def _compound_intents(q):
    out = []
    for k, it in _COMPOUND_CUES:
        if k in q and it not in out:
            out.append(it)
    return out


def _ordered_tasks(q):
    """按**出现顺序**抽取任务线索，返回 [(label, intent)]（去重）。"""
    found = []
    for k, it in _COMPOUND_CUES:
        i = q.find(k)
        if i >= 0:
            found.append((i, k, it))
    found.sort()
    out, seen = [], set()
    for _, k, it in found:
        if it in seen:
            continue
        seen.add(it)
        out.append((k, it))
    return out


_CLAUSE_SPLIT = None


def _topic_of(clause):
    """给一个子句判定主题：强关键词 → 复合线索 → 分类器（高置信）。"""
    for k, it in STRONG:
        if k in clause:
            return it
    for k, it in _COMPOUND_CUES:
        if k in clause:
            return it
    try:
        it, conf = classify(clause)
        if conf >= 0.5 and it not in ("oos", "greet"):
            return it
    except Exception:  # noqa: BLE001
        pass
    return None


def _clause_tasks(q):
    """自然口语的多维提问：按子句切分，逐一判主题，得到有序任务清单（去重）。"""
    parts = re.split(r"[，,；;。!！?？]+|还有|还有呢|以及|顺便|另外|再有|然后再|再说|同时|并且", q)
    out, seen = [], set()
    for p in parts:
        p = (p or "").strip()
        if len(p) < 2:
            continue
        it = _topic_of(p)
        if it and it not in seen:
            seen.add(it)
            out.append((p[:12], it))
    return out


_CANCEL = {"算了", "不问了", "不用了", "取消", "没事了", "不查了"}


def _final_guard(q, txt):
    """P0：输出业务校验——非春采期禁采摘措辞；指定日期须落到位；去占位。"""
    txt = season.clean_text(txt)
    if season.is_off():
        for k in ["可正常采", "适合采", "建议采摘", "优先采", "先采"]:
            if k in txt:
                txt = season.care_hint() + "（" + txt.replace(k, "暂不推荐采摘") + "）"
                break
    try:
        from . import nlg
        ad = nlg._parse_abs_date(q)
    except Exception:  # noqa: BLE001
        ad = None
    if ad is not None:
        iso = ad.isoformat()
        if iso not in txt and "超出" not in txt and "不在" not in txt:
            txt += f"（目标日期 {iso}）"
    return txt


def _extract_state(q, history, r, base=None):
    """从问题/回答抽取槽位，并以传入 state 为**基底合并**（避免丢失 active_date）。"""
    st = dict(base or {})
    st["intent"] = r.get("intent")
    try:
        from . import nlg
        flds = _parse_fields(q)
        if flds:
            st["fields"] = flds
        ad = nlg._parse_abs_date(q)
        if ad is None and r.get("text"):
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", r["text"])
            if m:
                import datetime as _dt
                ad = _dt.date.fromisoformat(m.group(1))
        if ad is not None:
            st["active_date"] = ad.isoformat()
    except Exception:  # noqa: BLE001
        pass
    if re.search(r"json", q or "", re.I):
        st["format"] = "json"
    elif any(k in (q or "") for k in ["表格", "markdown", "Markdown"]):
        st["format"] = "table"
    return st


_KNOWN_FIELDS = {"date", "tmin", "tmax", "temp", "rain", "precip", "risk", "risk_level", "risk_r",
                 "action", "suitability", "p_frost", "p_heat"}

# 中文列名/字段名 → 规范化键（用于"列：日期、最低温、降雨、风险、行动"这类请求）
_CN2FIELD = [("最低气温", "tmin"), ("最低温度", "tmin"), ("最低温", "tmin"),
             ("最高气温", "tmax"), ("最高温度", "tmax"), ("最高温", "tmax"),
             ("降雨", "rain"), ("降水", "rain"), ("雨量", "rain"),
             ("适宜度", "suitability"), ("霜冻概率", "p_frost"), ("高温概率", "p_heat"),
             ("风险等级", "risk"), ("风险", "risk"), ("行动", "action"), ("措施", "action"), ("建议", "action"),
             ("日期", "date"), ("时间", "date")]
_FIELD_CUES = ("字段", "列", "表头", "包含")


def _parse_fields(q):
    """解析用户指定字段：英文（date,tmin,…）与中文（日期、最低温、降雨、风险、行动）。"""
    q = q or ""
    m = re.search(r"字段[为是:：]?\s*([A-Za-z_,\s/]+)", q)
    seg = m.group(1) if m else q
    sel = [t for t in (t.lower() for t in re.findall(r"[A-Za-z_]+", seg)) if t in _KNOWN_FIELDS]
    if any(c in q for c in _FIELD_CUES):
        cue = min([q.find(c) for c in _FIELD_CUES if c in q])
        tail = q[cue:]
        hits = sorted((tail.find(k), v) for k, v in _CN2FIELD if k in tail)
        for _, v in hits:
            if v not in sel:
                sel.append(v)
    return list(dict.fromkeys(sel)) or None


def answer(question, context=None, history=None, state=None):
    q = _normalize(question)
    r = _answer_impl(q, context, history, state)
    try:
        st = _extract_state(q, history, r, state)
        if isinstance(r.get("state"), dict):
            st.update(r["state"])
        from . import nlg
        ctx = nlg.classify_ctx(_load_data(), q)
        fields = _parse_fields(question) or (st.get("fields") if isinstance(st, dict) else None)
        if fields:
            st["fields"] = fields
        q2 = q
        try:
            if st.get("active_date") and nlg._parse_abs_date(q) is None:
                q2 = q + " " + str(st["active_date"])
        except Exception:  # noqa: BLE001
            pass
        if st.get("format") == "json":
            obj = nlg.structured_answer(ctx, q2, fields)
            if obj is not None:
                r["text"] = json.dumps(obj, ensure_ascii=False)
                r["format"] = "json"
        elif st.get("format") == "table":
            rows = nlg.structured_rows(ctx, q2, fields)   # 统一行数组：多日/指定列都从这里来
            if not rows:
                obj = nlg.structured_answer(ctx, q2, fields)
                rows = obj.get("days") or ([obj] if isinstance(obj, dict) and obj.get("date") else [])
            tbl = nlg.markdown_table(rows, fields)
            if tbl:
                r["text"] = tbl
                r["format"] = "table"
        if isinstance(r.get("text"), str) and r.get("format") not in ("json", "table") and r.get("intent") not in ("cancel", "memory"):
            r["text"] = _final_guard(q, r["text"])
        r["state"] = st
    except Exception:  # noqa: BLE001
        pass
    return r


def _answer_impl(question, context=None, history=None, state=None):
    data = _load_data()
    q0 = (question or "").strip()
    if not q0:
        return _reply("请描述你的问题，例如：今天有风险吗、要不要防冻、先采哪块地、保险多少钱一亩。")
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in q0)
    if not has_cjk and any(c.isalpha() for c in q0):
        return _reply("This assistant currently supports Chinese only. 请用中文提问，例如：今天有风险吗？")
    # 半英文（大量英文 + 少量中文）不下猜测：明确拒绝，避免"半翻译"误答
    latin = len(re.findall(r"[A-Za-z]", q0)); cjk = len(re.findall(r"[\u4e00-\u9fff]", q0))
    if latin >= 12 and cjk < latin:
        return _reply("检测到较多英文。本助手目前仅支持中文（含常见中英术语，如 frost/risk）；"
                      "请用中文提问，例如：今天有风险吗 / 明天要不要防冻 / 先采哪块地。")
    if any(w in q0 for w in OFFTOPIC):
        return _reply("抱歉，我只服务梅家坞茶园的气候风险与采摘决策（如：风险、防冻、灌溉、采摘、保险、开采期）。"
                      "健康/金融等非农业问题请咨询专业人员。")
    if (("温度" in q0 or "气温" in q0 or "降雨" in q0 or "降水" in q0)
            and ("个月" in q0 or "季度" in q0 or "半年" in q0 or "一年" in q0)):
        return _reply("我们只能给出 16 天逐日预报与逐月气候概率（历史统计），"
                      "无法准确预测三个月后的逐日气温/降雨；更远的趋势请参考气候概率或官方季节预测。")
    # 结构化上下文：上一条 user 与上一条 assistant（结论），并提取实体（目标日期）
    prev = ""
    prev_assistant = ""
    if history:
        for m in reversed(history):
            if m.get("role") == "user" and not prev:
                prev = m.get("content", "") or ""
            if m.get("role") == "assistant" and not prev_assistant:
                prev_assistant = m.get("content", "") or ""
            if prev and prev_assistant:
                break
    stripped = _strip_negations(question)
    state = dict(state or {})
    ctx_summary = (state.get("summary") or "") if isinstance(state, dict) else ""
    CONTINUE = {"继续", "然后", "然后呢", "接着", "接着说", "还有", "还有呢", "那呢", "继续呢", "接下来"}
    if q0 in CONTINUE and not prev:
        return _reply("请先告诉我想了解哪方面（如：今天风险、要不要防冻、先采哪块地），我再继续。")

    # 对话记忆：直接回答"刚刚我问了什么 / 你刚才回答了什么"（history 由前端携带）
    if prev and any(k in question for k in ["刚刚我问", "我刚才问", "我刚才说", "上一个问题", "上一轮问",
                                            "我之前问", "我问了什么", "刚问了什么", "前面的问题", "上一个问"]):
        return _reply(f"你上一条问的是：「{prev}」。", intent="memory", chain=["会话记忆: 上一轮用户问题"])
    if prev_assistant and any(k in question for k in ["上一条回答", "上一个回答", "刚才回答", "你刚说", "你说了什么",
                                                      "刚刚回答了什么", "你的上一条回答"]):
        tail = "…" if len(prev_assistant) > 140 else ""
        return _reply("我上一条回答是：「" + prev_assistant[:140] + tail + "」。", intent="memory",
                      chain=["会话记忆: 上一轮回答"])
    if any(k in question for k in ["刚刚我问", "我刚才问", "我问了什么", "上一个问题"]) and not prev:
        if ctx_summary:
            return _reply("会话摘要（较早轮次）：「" + ctx_summary[:160] + "」。最近一轮见下方记录。", intent="memory",
                          chain=["会话记忆: 滚动摘要"])
        return _reply("这是第一轮，你还没有问过上一个问题。可以问我：今天有风险吗 / 要不要防冻 / 先采哪块地。",
                      intent="memory")

    # 任务引用：定位上一轮复合回答的"第 N 项"（如"第二项展开说明，并给行动建议"）
    _tm = re.search(r"第\s*([一二三四五六七八九十\d]+)\s*[项个条]", question)
    if _tm and isinstance(state, dict) and state.get("task_results"):
        try:
            from . import nlg as _nt
            tok = _tm.group(1)
            idx = int(tok) if tok.isdigit() else _nt._cn2num(tok)
        except Exception:  # noqa: BLE001
            idx = int(_tm.group(1)) if _tm.group(1).isdigit() else None
        tr = next((x for x in state["task_results"] if x.get("idx") == idx), None) if idx else None
        if tr:
            body = tr.get("text", "")
            if any(k in question for k in ["行动", "建议", "怎么办", "措施", "怎么处理", "应对"]):
                try:
                    from . import nlg as _na
                    rr = _na.compose(tr["intent"], question, _slots(question, data), data)
                    if rr.get("text") and rr["text"] not in body:
                        body = body + "\n行动建议：" + rr["text"]
                except Exception:  # noqa: BLE001
                    pass
            return _reply(f"第 {idx} 项（{tr.get('label', '')}）：{body}", intent="task_ref",
                          chain=[f"任务引用: 第{idx}项 {tr.get('intent')}"])

    active_date = state.get("active_date")
    mrel = re.search(r"(前一天|前一日|昨天|昨日|前日)", question)
    mrel2 = re.search(r"(后一天|次日|第二天|下一天|翌日)", question)
    mshift = -1 if mrel else (1 if mrel2 else None)
    if "大前天" in question:
        mshift = -3
    elif "前两天" in question:
        mshift = -2
    if active_date and mshift is not None:
        try:
            d0 = datetime.date.fromisoformat(str(active_date)[:10])
            active_date = (d0 + datetime.timedelta(days=mshift)).isoformat()
            state["active_date"] = active_date
        except Exception:  # noqa: BLE001
            pass
    carry = active_date or ""
    if not carry:
        mm = re.search(r"(20\d{2}-\d{2}-\d{2})", prev + " " + prev_assistant) or \
            re.search(r"(\d{1,2})月(\d{1,2})日", prev_assistant)
        if mm:
            carry = mm.group(1) if (mm.lastindex or 1) <= 1 else f"{season.today().year}年{int(mm.group(1))}月{int(mm.group(2))}日"
    pronoun = any(k in question for k in ["那一天", "那天", "它的", "这个", "该日", "它", "前一天", "后一天", "次日"])
    # 指代"那一天采取什么措施"：直接按上一目标日给行动
    if pronoun and carry and any(k in question for k in ["措施", "怎么办", "做什么", "咋办", "应对", "怎么处理"]):
        dd = next((d for d in data["days"] if d["date"] == carry), None)
        if dd is not None:
            try:
                from . import nlg as _nlg
                return {"engine": "teawindow-own", "mode": "rules", "intent": "day_action", "confidence": 0.7,
                        "backend": intent_backend(), "retrieval": retrieval_backend(), "slots": {}, "detail": False,
                        "follow_up": True, "text": _nlg.day_advice(dd, season.is_off()),
                        "chain": ["指代: 上一目标日 " + carry]}
            except Exception:  # noqa: BLE001
                pass

    follow_marks = ["呢", "那", "这个", "它", "详细", "展开", "为什么", "依据", "具体", "原因"]
    is_follow = (len(question) <= 12) and any(t in question for t in follow_marks) and not _strong_intent(stripped)
    qt = question
    if (is_follow or pronoun) and prev:
        qt = question + " " + prev
    elif (is_follow or pronoun) and ctx_summary:
        qt = question + " " + ctx_summary
    # 本轮若含相对日期（明天/后天/第N天），以本轮为准（避免被上一轮的"明天"覆盖成"后天"）
    try:
        from . import nlg as _nq
        _off_q = _nq._day_offset(question)
    except Exception:  # noqa: BLE001
        _off_q = None
    if _off_q is not None:
        try:
            target_q = (season.today() + datetime.timedelta(days=int(_off_q))).isoformat()
            qt = question + " " + target_q + ((" " + prev) if prev else "")
            state["active_date"] = target_q
        except Exception:  # noqa: BLE001
            pass
    # （相对日期强制按日回答放在 strong/kw 计算之后）
    if carry and (is_follow or pronoun):
        qt = qt + " " + carry
    qt_s = _strip_negations(qt)

    intent, conf = classify(qt_s)
    strongs = _strong_all(stripped) or _strong_all(qt_s)
    strong = strongs[0] if strongs else None
    kw = _keyword_intent(qt_s)
    # 纯相对日期追问（如"大后天呢"）无强/关词时，强制按日回答
    if _off_q is not None and not strong and not kw:
        intent, conf = "risk_today", 0.9
    # 日期承接追问（前一天/下一天/那一天/它…）无明确主题时，也强制按日回答，避免被判成无关意图
    if (mshift is not None or (pronoun and not prev)) and not strong and not kw:
        intent, conf = "risk_today", 0.85

    # 通用复合拆解：主题强意图 + 复合线索（风险/来源/模型/动作/具体灾害）
    comp = [x for x in dict.fromkeys(
        [s for s in strongs if s not in ("forecast_list", "rain_max", "compare", "greet")] + _compound_intents(stripped)
    ) if x not in ("oos", "unknown", "greet")]
    has_sep = any(sep in question for sep in ["、", ",", "，", "和", "同时", "以及", "还有"])
    if q0 in _CANCEL:
        return _reply("好的，已取消上一个问题。你可以继续问：今天风险 / 要不要防冻 / 先采哪块地 / 天气逐日。", intent="cancel")
    tasks = _ordered_tasks(stripped)
    if len(tasks) < 2:                       # 自然口语多维提问：按子句规划
        tasks = _clause_tasks(stripped)
    # 取消/改口（最后指令优先）：REMOVE 被取消任务，ADD 新任务
    try:
        removed = []
        for m in re.finditer(r"(?:取消|(?<!要)不要|不查|去掉|不再|算了)\s*(?:的)?\s*(霜冻|倒春寒|高温|干旱|灌溉|浇水|排水|降雨|雨水|防冻|保险|风险|开采|排班|采摘)", stripped):
            kw = m.group(1)
            for k, it in _COMPOUND_CUES:
                if k == kw and it not in removed:
                    removed.append(it)
            if kw == "防冻" and "frost" not in removed:
                removed.append("frost")
        if removed:
            tasks = [t for t in tasks if t[1] not in removed]
            state["tasks"] = [x for x in (state.get("tasks") or []) if x not in removed]
    except Exception:  # noqa: BLE001
        pass
    # 任务清单审计：存在"最大降雨"时不再单列通用"降雨"；存在"更新时间/来源"时不再单列"数据来源"
    _its = [t[1] for t in tasks]
    if "rain_max" in _its:
        tasks = [t for t in tasks if t[1] != "rain"]
    if "ops" in _its:
        tasks = [t for t in tasks if t[1] != "data_source"]
    if not is_follow and (len(tasks) >= 3 or (len(tasks) >= 2 and has_sep)):
        try:
            from . import nlg as _nlg
        except Exception:  # noqa: BLE001
            _nlg = None
        if _nlg is not None:
            results = []
            for idx, (label, it) in enumerate(tasks[:5], 1):
                rr = _nlg.compose(it, qt, _slots(qt, data), data)
                results.append({"idx": idx, "label": label, "intent": it, "text": rr["text"]})
            head = "按你的要求逐项回答：\n" + "\n".join(
                f"{x['idx']}) {x['label']}：{x['text']}" for x in results)
            used = [x["intent"] for x in results]
            return {"engine": "teawindow-own", "mode": "rules", "intent": "+".join(used),
                    "confidence": 0.9, "backend": intent_backend(), "retrieval": retrieval_backend(),
                    "slots": {}, "detail": False, "follow_up": False,
                    "text": _nlg.season.clean_text(head),
                    "chain": ["任务规划(有序): " + "+".join(used)],
                    "state": {"tasks": used, "task_results": results}}

    if strong:
        intent, conf = strong, 0.9            # 强关键词：置信度稳定（避免前后不一致）
    elif conf < 0.8 and kw:
        intent, conf = kw, 0.85               # 关键词命中：稳定
    # 检索增强（RAG 思路）：低置信/疑似域外时用近邻意图做回退或澄清
    retr = None
    _fmt_state = isinstance(state, dict) and state.get("format") in ("json", "table")
    if not strong and not kw and not _fmt_state:   # 结构化格式将由渲染器处理，跳过检索回退（省时延）
        retr = _retrieval_nearest(qt)
        top = retr[0] if retr else None
        in_scope = bool(top and top["intent"] not in ("oos", "greet") and top["sim"] >= RETR_ADOPT)
        if intent == "oos":
            if in_scope:
                intent, conf = top["intent"], max(conf, 0.55)   # 召回恢复
            else:
                return _reply("这个问题超出我的能力范围：我只服务梅家坞茶园的气候风险与采摘/养护决策"
                              "（风险、防冻、灌溉、采摘窗口、保险、开采期等）。其他问题请咨询相应专业人员。",
                              intent="oos", chain=["拒识: 域外(K+1 分类)"])
        elif conf < 0.5:
            if in_scope:
                intent, conf = top["intent"], max(conf, 0.55)
            else:
                opts = [x for x in (retr or []) if x["intent"] not in ("oos", "greet")]
                if opts:
                    cand = "、".join(dict.fromkeys(x["intent"] for x in opts[:2]))
                    return _reply(f"我不太确定你的问题。你更想问的是：{cand}？"
                                  "也可以直接问：今天有风险吗 / 要不要防冻 / 先采哪块地 / 保险多少钱一亩。")
                return _reply("我不太确定你的问题。可以这样问：今天有风险吗 / 要不要防冻 / 先采哪块地 / 保险多少钱 / 今年什么时候开采。")
    sl = _slots(qt, data)
    try:
        from . import nlg
    except Exception:  # noqa: BLE001
        import nlg  # type: ignore
    res = nlg.compose(intent, qt, sl, data)
    return {"engine": "teawindow-own", "mode": "rules", "intent": intent, "confidence": round(conf, 2),
            "backend": intent_backend(), "retrieval": retrieval_backend(),
            "slots": sl, "detail": bool(res.get("detail")), "follow_up": bool(is_follow),
            "text": res["text"], "chain": res["chain"],
            "state": {k: v for k, v in (("active_date", state.get("active_date")), ("tasks", state.get("tasks"))) if v is not None}}


if __name__ == "__main__":
    for q in ["今天有风险吗", "要不要防冻", "先采哪块地", "保险多少钱", "今年什么时候开采", "你们用什么模型"]:
        r = answer(q)
        print(f"[{r['intent']} {r['confidence']}] {q}\n  -> {r['text']}\n")
