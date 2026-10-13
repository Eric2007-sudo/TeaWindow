"""
M1 自研 NLG：结论先行、条件分支、多变体、数值接地、简洁/详细分档。
纯规则生成（无外部 LLM）。所有数字来自本项目 data.json 与模型输出。
"""
import hashlib
import datetime

# "详细"触发词（可扩展）
DETAIL_TRIGGERS = ["详细", "为什么", "为什么", "依据", "展开", "展开说", "具体", "原因",
                   "明细", "怎么算", "如何得出", "说明一下", "解释", "多点", "详细点", "依据是"]


def want_detail(q):
    return any(t in q for t in DETAIL_TRIGGERS)


def _seed(q, extra=""):
    return int(hashlib.md5((q + extra).encode("utf-8")).hexdigest(), 16)


def _pick(items, q, extra=""):
    return items[_seed(q, extra) % len(items)]


def current_day(days):
    today = datetime.date.today().isoformat()
    m = [d for d in days if d["date"] == today]
    if m:
        return m[0]
    past = [d for d in days if d["date"] <= today]
    return past[-1] if past else days[-1]


def classify_ctx(data, q):
    days = data["days"]
    fc = [d for d in days if d["source"] == "forecast"]
    hist = [d for d in days if d["source"] == "history"]
    cur = current_day(days)
    H = _horizon(q) or 7
    return {"data": data, "fc": fc, "hist": hist, "cur": cur, "H": H}


def _horizon(q):
    import re
    m = re.search(r"(\d+)\s*天", q)
    if m:
        return int(m.group(1))
    if "一个月" in q or "30天" in q or "1个月" in q:
        return 30
    if "半个月" in q:
        return 15
    if "两周" in q:
        return 14
    if "一周" in q:
        return 7
    return None


def _min_tmin(sub):
    if not sub:
        return None, None
    d = min(sub, key=lambda x: x["tmin"])
    return d["tmin"], d["date"]


def _max_tmax(sub):
    if not sub:
        return None, None
    d = max(sub, key=lambda x: x["tmax"])
    return d["tmax"], d["date"]


def _max_pf(sub):
    if not sub:
        return 0.0, None
    d = max(sub, key=lambda x: (x.get("p_frost") or 0))
    return (d.get("p_frost") or 0), d["date"]


def _max_ph(sub):
    if not sub:
        return 0.0, None
    d = max(sub, key=lambda x: (x.get("p_heat") or 0))
    return (d.get("p_heat") or 0), d["date"]


def _clim_risk(data, months, key):
    clim = data.get("climatology", {}).get("monthly", [])
    vs = [c[key] for c in clim if c["month"] in months]
    return max(vs) if vs else 0.0


def _months_of(H):
    today = datetime.date.today()
    return sorted({(today + datetime.timedelta(days=k)).month for k in range(H + 1)})


# ---------------------------------------------------------------- 各意图
def frost(ctx, q, detail):
    fc, H = ctx["fc"], ctx["H"]
    sub = fc[:min(H, len(fc))]
    tmin, dmin = _min_tmin(sub)
    pf, d_pf = _max_pf(sub)
    need = (pf > 0.2) or (tmin is not None and tmin <= 2)
    if not need:
        lead = _pick([f"不用防冻。", f"目前无需防冻。", f"这几天不用防冻。"], q)
        base = (f"未来 {H} 天最低 Tmin {tmin}℃（{dmin}），无霜冻风险；达标芽叶可正常采。"
                if tmin is not None else "预报期内无霜冻风险；可正常采。")
        text = lead + base
    else:
        lead = _pick([f"要防冻。", f"需重点防冻。", f"建议提前防冻。"], q)
        text = lead + f" {d_pf} 前后有霜冻风险（P={pf:.2f}，Tmin {tmin}℃）。夜晨覆盖/熏烟/喷水，达标芽先抢采。"
    if H > 16:
        months = _months_of(H)
        cp = _clim_risk(ctx["data"], months, "frost_day_prob")
        text += f" 超出16天无逐日预报；{'、'.join(str(m) for m in months)}月历史霜冻日概率约 {cp*100:.0f}%。"
    chains = ["数据: Open-Meteo 16天预报 + 逐月气候概率", "模型: 霜冻/倒春寒 + 集合 P(霜冻)"]
    if detail:
        text += (f" 依据：预报期最低 Tmin={tmin}℃@{dmin}，最高霜冻概率 P={pf:.2f}（@{d_pf}）；"
                 f"当前日 Tmin={ctx['cur']['tmin']}℃。阈值：Tmin≤2℃ 记霜冻、≤4℃且前期偏暖记倒春寒。")
    return text, chains


def heat(ctx, q, detail):
    fc, H = ctx["fc"], ctx["H"]
    sub = fc[:min(H, len(fc))]
    tmax, dmax = _max_tmax(sub)
    ph, d_ph = _max_ph(sub)
    need = (ph > 0.2) or (tmax is not None and tmax >= 33)
    if not need:
        text = _pick(["不用遮阳。", "暂不用遮阳。", "不用防高温。"], q) + f" 未来 {H} 天最高 Tmax {tmax}℃（{dmax}），无高温胁迫。"
    else:
        text = _pick(["建议遮阳。", "注意高温。", "要防热害。"], q) + f" {d_ph} 前后 Tmax 可达 {tmax}℃（P={ph:.2f}）。上遮阳网、傍晚浇透水、避免正午修剪。"
    chains = ["数据: Open-Meteo + 集合预报", "模型: 高温/干旱复合"]
    if detail:
        text += f" 依据：预报期最高 Tmax={tmax}℃@{dmax}，P(高温) 最高 {ph:.2f}@{d_ph}。"
    return text, chains


def drought(ctx, q, detail):
    cur = ctx["cur"]
    dry, deficit, soil = cur.get("dry_run", 0), cur.get("deficit", 0), cur.get("soil", 1)
    need = (dry >= 5) or (deficit is not None and deficit >= 45) or (soil is not None and soil < 0.25)
    if not need:
        text = _pick(["暂不用灌溉。", "不用急着浇水。", "水分尚可。"], q) + f" 已连旱 {dry} 天、水分亏缺 {deficit}，暂无明显旱情。"
    else:
        text = _pick(["建议灌溉。", "要补水。", "该浇一次水了。"], q) + f" 已连续 {dry} 天少雨、水分亏缺 {deficit}（土壤 {soil}）；早晚浇透根层、稻草覆盖保墒，优先幼龄/向阳坡。"
    chains = ["数据: Open-Meteo", "模型: 干旱(水分亏缺+土壤湿度)"]
    if detail:
        text += " 依据：dry_run、10日水分亏缺(ET0−降水)、0–7cm 土壤含水量；连旱≥5 天或亏缺≥45 记干旱。"
    return text, chains


def rain(ctx, q, detail):
    cur = ctx["cur"]; fc, H = ctx["fc"], ctx["H"]
    wet = cur.get("wet_run", 0)
    rain_next = sum((d.get("precip") or 0) for d in fc[:min(H, len(fc))])
    need = (wet >= 4) or (rain_next >= 25)
    if not need:
        text = _pick(["不用特别防雨。", "雨水影响不大。"], q) + f" 近期连雨 {wet} 天、未来 {H} 天累计降水约 {rain_next:.0f}mm。"
    else:
        text = _pick(["注意排水防涝。", "要防连阴雨。"], q) + f" 连雨 {wet} 天、未来 {H} 天累计约 {rain_next:.0f}mm；清沟排水防沤根，鲜叶及时摊青。"
    chains = ["数据: Open-Meteo", "模型: 连阴雨指标"]
    if detail and fc:
        text += f" 依据：连阴雨日数 {wet}，预报期累计降水 {rain_next:.0f}mm。"
    return text, chains


def _season():
    """春采季：3–4月（西湖龙井 43 核心）；其余为非春采期。"""
    m = datetime.date.today().month
    return "spring" if m in (3, 4) else "off"


def pick_window(ctx, q, detail):
    data = ctx["data"]; cur = ctx["cur"]
    if _season() == "off":
        return ("当前为非春采期（西湖龙井 43 春采季为 3–4 月），本工具此时以**园间养护**为主："
                "关注防霜冻/干旱/连阴雨，规划修剪、施肥、清沟与越冬管理，暂不推荐春茶采摘窗口。",
                ["季节约束: 非春采期"])
    best = data.get("decision", {}).get("best_pick_day", "-")
    wins = data.get("pick_window", [])
    suit = cur.get("suitability", 0)
    ok = suit >= 40
    text = _pick(["今天适合采。" if ok else "今天不太适合采。"], q) + f" 今日适宜度 {suit}；推荐最佳采摘日 {best}" + \
           (f"（适宜度 {wins[0]['suitability']}）。" if wins else "。")
    if detail and wins:
        text += " 未来适宜度前3：" + "、".join(f"{w['date']}({w['suitability']})" for w in wins[:3]) + "。"
    return text, ["模型: 采摘适宜度"]


def schedule(ctx, q, detail):
    if _season() == "off":
        return ("当前为非春采期，暂不提供采摘排班；建议转为**养护排期**："
                "防冻/防旱/排涝巡查 + 修剪、施肥、清沟与越冬准备。", ["季节约束: 非春采期"])
    sch = (ctx["data"].get("schedule", {}) or {}).get("schedule", [])
    if not sch:
        return "暂无排班数据。", ["模型: 采摘调度"]
    first = sch[0]["plots"]
    names = "、".join(p["name"] for p in first)
    text = _pick(["先采：" if False else "建议先采：", "优先采：", "第一优先："], q) + f"{names}（{sch[0]['date']}）"
    text += "。" + "；".join("、".join(p["name"] for p in s["plots"]) + f"（{s['date']}）" for s in sch[1:])
    if detail:
        text += " 依据：按每日产能约束 + 地块霜冻易感 + 适宜度排序。"
    return text, ["模型: 采摘调度优化"]


def decision(ctx, q, detail):
    dec = ctx["data"].get("decision", {})
    d0 = (dec.get("days") or [{}])[0]
    rec = d0.get("recommend", "-")
    text = _pick([f"建议{rec}。", f"今天的建议是：{rec}。"], q) + \
           f" 今日灾害概率 {d0.get('p_hazard')}；抢采EV {d0.get('ev_pick')} / 防护EV {d0.get('ev_protect')} / 等待EV {d0.get('ev_wait')}。"
    if detail:
        text += f" 最佳采摘日 {dec.get('best_pick_day')}。方法：对'抢采/等待/防护'计算期望效用并取最大。"
    return text, ["模型: 决策论期望效用"]


def plot(ctx, q, detail):
    plots = (ctx["data"].get("terrain", {}) or {}).get("plots", [])
    high = [p["name"] for p in plots if p.get("frost_risk") == "高"]
    text = f"最需关注（霜冻易感高）：{'、'.join(high) if high else '无'}。" + \
           f" 共 {len(plots)} 地块；北坡/低洼更易积冷受冻，抢采与防冻优先安排。"
    if detail:
        text += " 各地块：" + "、".join(f"{p['name']}({p['frost_risk']},{p['elev_m']}m)" for p in plots) + "。"
    return text, ["模型: 地形霜冻易感"]


def insurance(ctx, q, detail):
    ins = ctx["data"].get("insurance", {})
    text = f"指数保险参考：霜冻阈值 {ins.get('frost_threshold')} 度日、赔付 {ins.get('payout_frost')} 元/亩；" + \
           f"历史赔付年 {ins.get('fire_years')}/{ins.get('n_years')}，公平保费≈{ins.get('fair_premium_per_mu')} 元/亩。"
    if detail:
        text += " 思路：用客观气候指数触发自动理赔，不依赖人工查勘，可做地块级差异化定价。"
    return text, ["模型: 天气指数保险(客观指数)"]


def value(ctx, q, detail):
    v = ctx["data"].get("value", {})
    text = f"示意测算：亩产值约 {v.get('value_per_mu')} 元，期望损失≈{v.get('expected_loss_per_mu')} 元/亩·年，参考保费 {v.get('premium_per_mu')} 元/亩，工具减损≈{v.get('tool_benefit_per_mu')} 元/亩·年。"
    if detail:
        text += f" 依据：霜冻致损年概率 {v.get('p_frost')}、高温 {v.get('p_heat')}，亩产/价格/损失率为示意假设。"
    return text, ["模型: 价值闭环"]


def harvest_date(ctx, q, detail):
    ph = ctx["data"].get("phenology", {})
    if ph:
        text = f"今年（GDD 阈值 {ph.get('threshold')}℃·d）开采日预测约 {ph.get('predicted_date')}，对官方开采日 MAE≈{ph.get('mae')} 天。"
    else:
        text = "开采期由有效积温预测；近年官方开采日多在 3月13–20日。"
    if detail and ph:
        text += f" 方法：基温 {ph.get('base')}℃、起算 {ph.get('start')}，累计有效积温达阈值即预测开采。"
    return text, ["模型: GDD 物候", "真值: 官方开采日"]


def data_source(ctx, q, detail):
    kg = ctx["data"].get("_kg") or {}
    from . import engine as _e  # 复用 knowledge
    kg = _e._load_kg()
    if not detail:
        return "数据来自公开源：Open-Meteo(气象)、Meteostat(台站观测)、NASA GIBS/Sentinel-2(遥感)、Open-Meteo DEM(地形)。", ["本项目数据管线"]
    return "数据来源：" + "；".join(kg["data_sources"]) + "。", ["本项目数据管线"]


def model(ctx, q, detail):
    if not detail:
        return ("本问答为自研引擎：自训意图分类 + 接地生成，答案来自本项目数据与模型；"
                "核心为纯 numpy GBDT 复合风险（AUC 0.998），另有概率校准与集合不确定性。", ["自研模型与数据流"])
    from . import engine as _e
    kg = _e._load_kg()
    return "自研流程：" + "；".join(kg["model"] + kg["qa_engine"]) + "。", ["自研模型与数据流"]


def greet(ctx, q, detail):
    return "你好！可以问：今天风险、要不要防冻/灌溉、采哪块地、保险与损失、开采期等。", ["自研问答引擎"]


def fallback(ctx, q, detail):
    cur = ctx["cur"]
    return (f"我可以帮你看风险、防冻/灌溉、采摘窗口、采哪块地、保险与损失等。当前：{cur['date']} 风险 "
            f"{cur['risk_level']}，推荐采摘日 {ctx['data'].get('decision',{}).get('best_pick_day','-')}。",
            ["自研问答引擎"])


def day_advice(d):
    """按单日结构化结果生成结论先行的建议（与适宜度/风险严格一致，用于替换 LLM 日报）。"""
    concl = []
    dsh, heat = d.get("cold_shock"), d.get("heat")
    dry = (d.get("dry_run") or 0) >= 5 or (d.get("deficit") or 0) >= 45
    wet = (d.get("wet_run") or 0) >= 4 or (d.get("precip") or 0) >= 15
    suit = d.get("suitability") or 0
    tmin, tmax, precip = d.get("tmin"), d.get("tmax"), d.get("precip")
    if d.get("frost") or dsh:
        concl.append("防倒春寒/霜冻")
    if heat:
        concl.append("防高温")
    if dry:
        concl.append("防旱补水")
    if wet:
        concl.append("防连阴雨/排水")
    if not concl:
        if suit >= 40:
            concl.append("适合采")
        else:
            concl.append("暂不宜采")
    head = "、".join(concl) + "（" + f"风险{d.get('risk_level','-')}、适宜度{int(suit)}" + "）。"
    acts = []
    if d.get("frost") or dsh:
        acts.append(f"Tmin {tmin}℃，夜晨覆盖/熏烟并抢采达标芽叶")
    if heat:
        acts.append(f"Tmax {tmax}℃，上遮阳网、傍晚浇透水")
    if dry:
        acts.append(f"连旱{d.get('dry_run',0)}天/亏缺{d.get('deficit')}，早晚浇透并覆盖保墒")
    if wet:
        acts.append(f"连雨{d.get('wet_run',0)}天/降水{precip}mm，清沟排水、鲜叶及时摊青")
    if suit >= 40 and not (d.get("frost") or heat or dry or wet):
        acts.append("按一芽一叶标准采，鲜叶及时摊放")
    if not acts:
        acts.append("按常规管护，关注最新预报")
    text = head + " 建议：" + "；".join(acts) + "。"
    text += "（决策辅助，以官方预警与实况为准）"
    return text


HANDLERS = {
    "frost": frost, "heat": heat, "drought": drought, "rain": rain,
    "pick_window": pick_window, "schedule": schedule, "decision": decision, "plot": plot,
    "insurance": insurance, "value": value, "harvest_date": harvest_date,
    "data_source": data_source, "model": model, "greet": greet,
    "risk_today": None,  # 用下面通用
}


def compose(intent, q, sl, data):
    ctx = classify_ctx(data, q)
    detail = want_detail(q)
    if intent in HANDLERS and HANDLERS[intent]:
        text, chains = HANDLERS[intent](ctx, q, detail)
    elif intent == "risk_today":
        cur, fc, H = ctx["cur"], ctx["fc"], ctx["H"]
        n7 = fc[:7]
        mx = max(n7, key=lambda x: (x.get("risk_R") or 0)) if n7 else cur
        dom = []
        if cur.get("frost") or cur.get("cold_shock"):
            dom.append("霜冻/倒春寒")
        if cur.get("heat"):
            dom.append("高温")
        if (cur.get("dry_run") or 0) >= 5 or (cur.get("deficit") or 0) >= 45:
            dom.append("干旱/水分")
        if (cur.get("wet_run") or 0) >= 4:
            dom.append("连阴雨")
        domt = ("主要风险：" + "、".join(dom) + "。") if dom else "无明显主导风险。"
        text = _pick(["总体风险低。" if cur["risk_level"] == "低" else f"当前风险{cur['risk_level']}。"], q) + \
               f" {cur['date']} 风险 {cur['risk_level']}（R={cur['risk_R']}），适宜度 {cur['suitability']}；" + domt + \
               f" 未来7天最高在 {mx['date']}（{mx['risk_level']}）。"
        if detail:
            text += " 依据：复合风险 = 倒春寒/高温/干旱 取最大；阈值 R≥0.5 记风险日。"
        chains = ["数据: Open-Meteo+Meteostat", "模型: GBDT复合风险"]
    else:
        text, chains = fallback(ctx, q, detail)
    return {"text": text, "chain": chains, "detail": detail}
