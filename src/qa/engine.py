"""
A-3 自研问答引擎（纯 numpy，离线可跑）。
流程：意图分类(我们训练的模型) → 槽位抽取 → 读取我们项目的数据/模型 → 接地生成答案 + 来源链。
设计说明：答案来自**本项目数据与模型**（GBDT复合风险/GDD物候/指数保险/调度/决策），
不依赖外部大模型；DeepSeek 仅在显式 engine=llm 时作为可选增强。
"""
import json
import os
import re

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


def classify(q):
    m = _load_model()
    x = _vec(q, m["vocab"])
    z = m["W"] @ x + m["b"]
    p = np.exp(z - z.max()); p /= p.sum()
    i = int(p.argmax())
    return m["classes"][i], float(p[i])


def _slots(q, data):
    plots = [p["name"] for p in (data.get("terrain", {}) or {}).get("plots", [])]
    plot = next((p for p in plots if p in q), None)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})?\s*[日号]?", q)
    date = f"{m.group(1)}月{m.group(2)+'日' if m.group(2) else ''}" if m else None
    return {"plot": plot, "date": date}


def _fmt(lst):
    return "；".join(lst)


def compose(intent, q, sl, data):
    days = data["days"]
    fc = [d for d in days if d["source"] == "forecast"]
    hist = [d for d in days if d["source"] == "history"]
    cur = hist[-1]
    n7 = fc[:7]
    mx = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else cur
    chains = []
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
        pf = fc[0].get("p_frost") if fc else None
        text = f"当前无霜冻(最近日 Tmin={cur['tmin']}℃)。"
        if any(d.get("frost") for d in n7):
            d = next(d for d in n7 if d.get("frost"))
            text += f" 未来7天 {d['date']} 有霜冻风险（Tmin={d['tmin']}℃）。"
        else:
            text += " 未来7天暂无霜冻信号。"
        text += " 建议：达标芽叶优先抢采；夜晨低温可覆盖/熏烟/喷水防御。"
        return {"text": text, "chains": ["数据: Open-Meteo+Meteostat", "模型: 霜冻/倒春寒指标"]}
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


def answer(question, context=None):
    data = _load_data()
    intent, conf = classify(question)
    kw = _keyword_intent(question)
    if conf < 0.8 and kw:           # 中低置信度用关键词兜底（关键词更可靠）
        intent, conf = kw, max(conf, 0.8)
    sl = _slots(question, data)
    res = compose(intent, question, sl, data)
    return {"engine": "teawindow-own", "intent": intent, "confidence": round(conf, 2),
            "slots": sl, "text": res["text"], "chain": res["chains"]}


if __name__ == "__main__":
    for q in ["今天有风险吗", "要不要防冻", "先采哪块地", "保险多少钱", "今年什么时候开采", "你们用什么模型"]:
        r = answer(q)
        print(f"[{r['intent']} {r['confidence']}] {q}\n  -> {r['text']}\n")
