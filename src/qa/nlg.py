"""
M1 自研 NLG：结论先行、条件分支、多变体、数值接地、简洁/详细分档。
纯规则生成（无外部 LLM）。所有数字来自本项目 data.json 与模型输出。
"""
import hashlib
import datetime
import re

import season

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
    today = season.iso_today()
    m = [d for d in days if d["date"] == today]
    if m:
        return m[0]
    past = [d for d in days if d["date"] <= today]
    return past[-1] if past else days[-1]


def _parse_abs_date(q):
    """解析绝对日期：2026年10月20日 / 10月20日 / 2026-10-20 / 10-20（补当前年）。"""
    for pat in (r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?",
                r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})"):
        m = re.search(pat, q)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    for pat in (r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)"):
        m = re.search(pat, q)
        if m:
            try:
                return datetime.date(season.today().year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                return None
    return None


def _day_offset(q):
    for k, v in [("今天", 0), ("今日", 0), ("明天", 1), ("明日", 1), ("后天", 2), ("大后天", 3)]:
        if k in q:
            return v
    import re
    cn = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    m = re.search(r"第([一二两三四五六七八九十0-9]+)天", q)
    if m:
        t = m.group(1)
        return (int(t) - 1) if t.isdigit() else cn.get(t, 0)
    m = re.search(r"([0-9]+)\s*天后", q)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二两三四五六七八九十]+)\s*天后", q)
    if m:
        return cn.get(m.group(1))
    return None


def _focus_day(ctx, q):
    """返回 (day, label)。支持相对日期、绝对日期、历史日期。"""
    ad = _parse_abs_date(q)
    if ad is not None:
        iso = ad.isoformat()
        for d in ctx["fc"]:
            if d["date"] == iso:
                return d, iso
        for d in ctx["hist"]:
            if d["date"] == iso:
                return d, iso
        return None, iso  # 超出数据范围
    off = _day_offset(q)
    if off is None:
        return None, None
    if isinstance(off, float):
        off = int(round(off))
    target = (season.today() + datetime.timedelta(days=off)).isoformat()
    for d in ctx["fc"]:
        if d["date"] == target:
            return d, off
    for d in ctx["hist"]:
        if d["date"] == target:
            return d, off
    return None, off


def _day_label(off):
    if isinstance(off, str):
        return off
    return {0: "今天", 1: "明天", 2: "后天", 3: "大后天"}.get(off, f"{off}天后")


def _dlab(off, date):
    """避免绝对日期时出现“2026-10-20（2026-10-20）”重复。"""
    lab = _day_label(off)
    return lab if (isinstance(off, str) and off == date) else f"{lab}（{date}）"


def classify_ctx(data, q):
    days = data["days"]
    today = season.iso_today()
    # P0：所有"未来窗口"先过滤 date>=业务今天，再取 N 天
    fc = [d for d in days if d["source"] == "forecast" and d["date"] >= today]
    hist = [d for d in days if d["source"] == "history"]
    cur = current_day(days)
    H = _horizon(q) or 7
    return {"data": data, "fc": fc, "hist": hist, "cur": cur, "H": H}


def _horizon(q):
    import re
    m = re.search(r"(\d+)\s*小时", q)
    if m:
        return max(1, int(round(int(m.group(1)) / 24)))
    m = re.search(r"([一二两三四五六七八九十0-9]+)\s*天", q)
    if m:
        t = m.group(1)
        if t.isdigit():
            return int(t)
        cn = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        if t == "十":
            return 10
        if "十" in t:
            a, b = t.split("十", 1)
            return cn.get(a, 1) * 10 + cn.get(b, 0)
        return cn.get(t)
    for k, v in [("半个月", 15), ("两周", 14), ("一周", 7), ("一个月", 30)]:
        if k in q:
            return v
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
    t = season.today()
    return sorted({(t + datetime.timedelta(days=k)).month for k in range(H + 1)})


# ---------------------------------------------------------------- 各意图
def frost(ctx, q, detail):
    d, off = _focus_day(ctx, q)
    if off is not None and d is None and isinstance(off, str):
        return (_range_msg(off), ["数据范围: 聊天近180天+16天预报"])
    if d is not None:
        need = d.get("frost") or d.get("cold_shock")
        lab = _dlab(off, d["date"])
        if need:
            pick = "" if season.is_off() else "达标芽叶优先抢采。"
            return (f"{lab} 有霜冻/倒春寒风险（Tmin {d['tmin']}℃）。"
                    f"夜晨覆盖/熏烟/喷水。{pick}", ["数据: Open-Meteo", "模型: 霜冻/倒春寒"])
        tail = (" " + season.care_hint()) if season.is_off() else " 达标芽叶可正常采。"
        return (f"{lab} 无霜冻风险：Tmin {d['tmin']}℃，"
                f"霜冻概率 {d.get('p_frost', 0)}。{tail}", ["数据: Open-Meteo + 集合", "模型: 霜冻/倒春寒"])
    fc, H = ctx["fc"], ctx["H"]
    today = season.iso_today()
    fut = [d for d in fc if d["date"] >= today]
    sub = fut[:min(H, len(fut))]
    tmin, dmin = _min_tmin(sub)
    pf, d_pf = _max_pf(sub)
    need = (pf > 0.2) or (tmin is not None and tmin <= 2)
    if not need:
        lead = _pick(["不用防冻。", "目前无需防冻。", "这几天不用防冻。"], q)
        tail = (" " + season.care_hint()) if season.is_off() else "达标芽叶可正常采。"
        base = (f"未来 {H} 天最低 Tmin {tmin}℃（{dmin}），无霜冻风险；" + tail
                if tmin is not None else "预报期内无霜冻风险；" + tail)
        text = lead + base
    else:
        lead = _pick(["要防冻。", "需重点防冻。", "建议提前防冻。"], q)
        pick = "" if season.is_off() else "达标芽先抢采。"
        text = lead + f" {d_pf} 前后有霜冻风险（P={pf:.2f}，Tmin {tmin}℃）。夜晨覆盖/熏烟/喷水。{pick}"
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
    d, off = _focus_day(ctx, q)
    if off is not None and d is None and isinstance(off, str):
        return (_range_msg(off), ["数据范围: 聊天近180天+16天预报"])
    if d is not None:
        lab = _dlab(off, d["date"])
        need = (d.get("tmax") or 0) >= 33
        return (f"{lab} {'有高温风险' if need else '无高温风险'}"
                f"：Tmax {d['tmax']}℃。{'上遮阳网、傍晚浇透水。' if need else '可正常管理。'}",
                ["数据: Open-Meteo + 集合", "模型: 高温"])
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
    dry = cur.get("dry_run", 0) or 0
    deficit = cur.get("deficit", 0) or 0
    soil = cur.get("soil", None)
    bal = "水量盈余" if deficit < 0 else "水分亏缺"
    soil_need = (soil is not None and soil < 0.25)
    need_irrigate = (deficit >= 45) or soil_need
    if need_irrigate:
        text = _pick(["建议灌溉。", "要补水。", "该浇一次水了。"], q) + \
            f" 已连续 {dry} 天少雨、10日{bal} {abs(deficit):.1f}mm（土壤 {soil}，模式估计）；早晚浇透根层、稻草覆盖保墒，优先幼龄/向阳坡。"
    elif dry >= 5:
        # P0：低亏缺且无现场探头 → 先测墒，不直接命令灌溉
        text = ("建议先测量根层墒情，暂不直接灌溉。"
                f" 模式提示已连续 {dry} 天少雨，但 10 日{bal} {abs(deficit):.1f}mm 未达亏缺阈值（45mm）；"
                f"土壤含水 {soil}（Open-Meteo 模式估计，非田间实测）。若现场墒情低于地块阈值，再于早晚补水。")
    else:
        text = _pick(["暂不用灌溉。", "不用急着浇水。", "水分尚可。"], q) + \
            f" 已连旱 {dry} 天、10日{bal} {abs(deficit):.1f}mm（土壤含水 {soil}，模式估计），暂无明显旱情。"
    chains = ["数据: Open-Meteo（水分平衡=ET0−降水；负值为盈余）", "模型: 干旱(水分亏缺+土壤含水量·模式估计)"]
    if detail:
        text += " 依据：dry_run、10日水分平衡(ET0−降水)、0–7cm 土壤含水量；ET0−降水≥45mm 记亏缺。土壤水分为模式估计，非田间传感器。"
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
    """春采季：3–4月（西湖龙井 43 核心）；其余为非春采期。统一由 season.py 决定。"""
    return season.policy()["season"]


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
    if _season() == "off":
        return ("当前为非春采期，不做抢采/等待/防护的采摘决策；" + season.care_hint(),
                ["季节约束: 非春采期"])
    dec = ctx["data"].get("decision", {})
    days = dec.get("days") or []
    if not days:
        return ("暂无决策数据；当前如无风险可先安排养护，有霜冻/干旱风险时优先防护。",
                ["模型: 决策论期望效用"])
    d0 = days[0]
    rec = d0.get("recommend") or "观望"
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
    # 数据权威性深答：区分模式/台站/遥感/现场传感器与验证边界
    if any(k in q for k in ["传感器", "实测站", "探头", "实时", "现场"]):
        try:
            import store
            n = store.sensor_count()
        except Exception:  # noqa: BLE001
            n = 0
        return (f"当前在线现场传感器记录 {n} 条（/api/realtime 实时展示）。"
                "注意：页面土壤湿度来自 Open-Meteo 模式字段（0–7cm），**不是**茶园探头实测；"
                "模式估计、台站观测、遥感反演、现场传感器必须分别看待。",
                ["数据性质: 模式/台站/遥感/传感器区分", "披露: 现场实测站数"])
    if any(k in q for k in ["台站", "距离", "误差", "偏差", "多远", "杭州站"]):
        return ("台站为 Meteostat 杭州站（WMO 58457），距梅家坞约 7.1 km；"
                "对 ERA5：Tmin 偏差 +2.88℃（MAE 2.90℃）、Tmax +3.34℃（MAE 3.38℃）、降水 MAE 3.30mm（r≈0.71）。"
                "高相关说明趋势相似，但偏差量级接近霜冻阈值（2/4℃），不能据此断言地块级霜冻准确。"
                "当前线上风险**未采用**台站偏差订正（daily_corrected.csv 仅作交叉验证）。",
                ["来源: Meteostat WMO58457", "披露: 未用于当前预测"])
    if any(k in q for k in ["受灾", "产量", "品质", "验证", "标签", "真实", "盲测"]):
        return ("目前**没有**真实受灾/产量/品质的前瞻性验证：风险标签为专家规则（弱标签），"
                "AUC 属弱标签复现指标；事件回测仅 7 个正事件、无负事件与滚动预报回放。"
                "需完成完整春采季的田间盲测与地块级闭环才能证明业务效果。",
                ["披露: 无真实标签/无盲测"])
    if any(k in q for k in ["链接", "出处", "网站", "原始", "下载", "许可", "license"]):
        return ("上游来源（可核验）：Open-Meteo https://open-meteo.com/en/docs ；"
                "Meteostat https://dev.meteostat.net/ ；NASA GIBS https://gibs.earthdata.nasa.gov/ ；"
                "Copernicus Sentinel-2 https://documentation.dataspace.copernicus.eu/ 。"
                "聊天暂不返回每项原始字段/抓取时间戳的版本身份。",
                ["来源: 可点击链接", "局限: 无逐项版本"])
    kg = ctx["data"].get("_kg") or {}
    from . import engine as _e  # 复用 knowledge
    kg = _e._load_kg()
    if not detail:
        return "数据来自公开源：Open-Meteo(气象)、Meteostat(台站观测)、NASA GIBS/Sentinel-2(遥感)、Open-Meteo DEM(地形)。", ["本项目数据管线"]
    return "数据来源：" + "；".join(kg["data_sources"]) + "。", ["本项目数据管线"]


def model(ctx, q, detail):
    # 证据类追问：直接回答指标口径/误报漏报/局限，不复述宣传模板
    if any(k in q for k in ["误报", "漏报", "准确率", "AUC", "auc", "验证", "指标", "区别", "可信"]):
        return ("口径说明：页面展示的 R 为**专家规则风险**（由阈值规则生成）；GBDT 仅作辅助概率。"
                "AUC 0.998 是**弱标签复现指标**（标签由相近气象特征规则生成），不等于真实灾害准确率；"
                "测试集正样本仅 112，召回≈0.76，**约 24% 弱标签正例被漏检**。"
                "事件回测仅 7 个正事件、无负事件与滚动预报回放，尚不能给出真实误报率/提前量。"
                "结论：可复现规则，但真实预测精度需按完整春采季的前瞻性盲测验证。",
                ["披露: 弱标签复现 vs 真实业务指标", "局限: 无负事件/无盲测"])
    if not detail:
        return ("本问答为自研引擎：自训意图分类 + 接地生成，答案来自本项目数据与模型；"
                "核心为纯 numpy GBDT 复合风险（辅助概率），页面展示风险 R 为专家规则值；"
                "AUC≈0.998 属**弱标签复现指标**，不代表真实灾害预测准确率。", ["自研模型与数据流"])
    from . import engine as _e
    kg = _e._load_kg()
    return "自研流程：" + "；".join(kg["model"] + kg["qa_engine"]) + "。", ["自研模型与数据流"]


def greet(ctx, q, detail):
    return "你好！可以问：今天风险、要不要防冻/灌溉、采哪块地、保险与损失、开采期等。", ["自研问答引擎"]


def fallback(ctx, q, detail):
    cur = ctx["cur"]
    if _season() == "off":
        return (f"我可以帮你看风险、防冻/灌溉、养护安排、保险与损失等。当前：{cur['date']} 风险 "
                f"{cur['risk_level']}（适宜度 {cur.get('suitability','-')}）。" + season.care_hint(),
                ["自研问答引擎"])
    best = ctx["data"].get("decision", {}).get("best_pick_day") or "-"
    return (f"我可以帮你看风险、防冻/灌溉、采摘窗口、采哪块地、保险与损失等。当前：{cur['date']} 风险 "
            f"{cur['risk_level']}，推荐采摘日 {best}。",
            ["自研问答引擎"])


def day_advice(d, season_off=False):
    """按单日结构化结果生成结论先行的建议（与适宜度/风险严格一致，用于替换 LLM 日报）。"""
    concl = []
    dsh, heat = d.get("cold_shock"), d.get("heat")
    deficit = d.get("deficit") or 0
    soil = d.get("soil")
    dry = (deficit >= 45) or (soil is not None and soil < 0.25)
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
        if season_off:
            concl.append("非春采期·养护为主")
        elif suit >= 40:
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
        acts.append(f"亏缺{d.get('deficit')}mm/土壤{soil}，若现场墒情低于地块阈值再早晚浇透并覆盖保墒")
    elif (d.get("dry_run") or 0) >= 5:
        acts.append(f"连旱{d.get('dry_run',0)}天但亏缺未达阈值，建议先测根层墒情再决定是否补水")
    if wet:
        acts.append(f"连雨{d.get('wet_run',0)}天/降水{precip}mm，清沟排水、鲜叶及时摊青")
    if suit >= 40 and not (d.get("frost") or heat or dry or wet):
        acts.append("按一芽一叶标准采，鲜叶及时摊放")
    if not acts:
        acts.append("按常规管护，关注最新预报")
    text = head + " 建议：" + "；".join(acts) + "。"
    text += "（决策辅助，以官方预警与实况为准）"
    return text


def rain_max(ctx, q, detail):
    """‘哪天雨最大’：在预报期内按降水量排序，给出具体日期。"""
    fc, H = ctx["fc"], ctx["H"]
    today = season.iso_today()
    fut = [d for d in fc if d["date"] >= today]
    sub = fut[:H] if H else fut[:7]
    if not sub:
        return "暂无预报数据。", ["数据: Open-Meteo 16天预报"]
    d = max(sub, key=lambda x: (x.get("precip") or 0))
    text = (f"未来 {len(sub)} 天雨最大的是 {d['date']}（约 {d.get('precip')} mm，"
            f"风险 {d.get('risk_level')}）。雨天鲜叶含水高，注意及时摊青；低洼茶园清沟排水。")
    return text, ["数据: Open-Meteo 16天预报", "模型: 连阴雨指标"]


def compare(ctx, q, detail):
    """‘今天和明天哪个风险高’：直接比较两天。"""
    today = season.iso_today()
    tm = (season.today() + datetime.timedelta(days=1)).isoformat()
    a = next((d for d in ctx["fc"] if d["date"] == today), None) or ctx["cur"]
    b = next((d for d in ctx["fc"] if d["date"] == tm), None)
    if not b:
        return f"今天风险 {a.get('risk_level')}（R={a.get('risk_R')}）；暂无明日对比数据。", ["数据: Open-Meteo + 集合"]
    if (a.get("risk_R") or 0) >= (b.get("risk_R") or 0):
        hi, lo = a, b
    else:
        hi, lo = b, a
    text = (f"对比：今天 R={a.get('risk_R')}（{a.get('risk_level')}） vs 明天 R={b.get('risk_R')}（{b.get('risk_level')}）；"
            f"{hi['date']} 风险更高。可结合主导风险安排防冻/抗旱/排涝。")
    if season.is_off():
        text += " " + season.care_hint()
    return text, ["数据: Open-Meteo + 集合预报", "模型: 复合风险对比"]


def forecast_list(ctx, q, detail):
    fc, H = ctx["fc"], ctx["H"]
    today = datetime.date.today().isoformat()
    fut = [d for d in fc if d["date"] >= today]
    sub = fut[:min(H, len(fut))]
    if not sub:
        return "暂无预报数据。", ["数据: Open-Meteo 16天预报"]

    def dom(d):
        r = []
        if d.get("frost") or d.get("cold_shock"):
            r.append("霜冻")
        if d.get("heat"):
            r.append("高温")
        if (d.get("dry_run") or 0) >= 5 or (d.get("deficit") or 0) >= 45:
            r.append("干旱")
        if (d.get("wet_run") or 0) >= 4:
            r.append("连阴雨")
        return "/".join(r)
    lines = []
    for d in sub:
        dd = dom(d)
        lines.append(f"{d['date'][5:]} {d.get('risk_level')}(R={d.get('risk_R')}"
                     + (f"，{dd}" if dd else "") + f"，适宜度{int(d.get('suitability') or 0)})")
    worst = max(sub, key=lambda x: (x.get("risk_R") or 0))
    out = f"未来 {len(sub)} 天逐日风险（梅家坞）：\n- " + "\n- ".join(lines)
    out += f"\n最高风险：{worst['date']}（{worst.get('risk_level')}，R={worst.get('risk_R')}）。"
    if detail:
        out += " 等级口径：R<0.25 低 / 0.25–0.5 中 / 0.5–0.75 高 / ≥0.75 极高；风险类型取倒春寒/高温/干旱最大项。"
    return out, ["数据: Open-Meteo 16天预报", "模型: GBDT复合风险"]


FIELD_KW = ["最低", "最高", "温度", "气温", "降雨", "降水", "雨量", "霜冻", "概率",
            "风险", "适宜度", "风速", "湿度", "不确定", "区间", "多少"]


def _asks_fields(q):
    return sum(1 for k in FIELD_KW if k in q) >= 2


def _range_msg(iso):
    """区分'数据仓库范围'与'聊天当前加载范围'，避免自相矛盾文案。"""
    try:
        y = int(str(iso)[:4])
    except Exception:  # noqa: BLE001
        y = 0
    if y and y < 2015:
        return f"{iso} 早于气象数据起始（2015 年），无法查询。"
    return (f"{iso} 不在聊天当前加载范围（近 180 天历史 + 未来 16 天预报）；"
            f"数据仓库有 2015 至今，但聊天接口暂未接入按需历史查询。")


def day_detail(ctx, q, detail):
    """复合字段问题：所有字段使用同一个目标日/时段，避免混用时间窗口。"""
    d, off = _focus_day(ctx, q)
    if d is None:
        if isinstance(off, str):
            return _range_msg(off), ["数据范围: 聊天近180天+16天预报"]
        # 无目标日但有天数 → 逐日字段列表
        fc = ctx["fc"][:ctx["H"]]
        if fc:
            lines = [f"{x['date'][5:]} Tmax{x.get('tmax')}/Tmin{x.get('tmin')}℃ 雨{x.get('precip')}mm "
                     f"{x.get('risk_level')}(R={x.get('risk_R')})" for x in fc]
            return ("未来 %d 天逐日（温度/降雨/风险）：\n- " % len(fc)) + "\n- ".join(lines), \
                ["数据: Open-Meteo 16天预报", "模型: 复合风险"]
        return None
    lab = _dlab(off, d["date"])
    parts = []
    if d.get("tmin") is not None:
        parts.append(f"Tmin {d['tmin']}℃")
    if d.get("tmax") is not None:
        parts.append(f"Tmax {d['tmax']}℃")
    if d.get("precip") is not None:
        parts.append(f"降水 {d['precip']}mm")
    if d.get("p_frost") is not None:
        parts.append(f"P(霜冻) {d['p_frost']}")
    elif d.get("frost") is not None:
        parts.append("霜冻 " + ("有" if d.get("frost") else "无"))
    if d.get("p_heat") is not None:
        parts.append(f"P(高温) {d['p_heat']}")
    parts.append(f"风险 {d.get('risk_level')}（R={d.get('risk_R')}）")
    parts.append(f"适宜度 {int(d.get('suitability') or 0)}")
    text = f"{lab}：" + "，".join(parts) + "。"
    if d.get("tmin_lo") is not None:
        text += f" 集合区间：Tmin {d['tmin_lo']}–{d['tmin_hi']}℃、Tmax {d['tmax_lo']}–{d['tmax_hi']}℃。"
    if season.is_off():
        text += " " + season.care_hint()
    return text, ["数据: Open-Meteo 逐日+集合（同一目标日口径）", "模型: 复合风险"]


HANDLERS = {
    "frost": frost, "heat": heat, "drought": drought, "rain": rain,
    "pick_window": pick_window, "schedule": schedule, "decision": decision, "plot": plot,
    "insurance": insurance, "value": value, "harvest_date": harvest_date,
    "data_source": data_source, "model": model, "greet": greet,
    "forecast_list": forecast_list, "rain_max": rain_max, "compare": compare,
    "risk_today": None,  # 用下面通用
}


def compose(intent, q, sl, data):
    ctx = classify_ctx(data, q)
    detail = want_detail(q)
    # 复合字段问题（含目标日/时段 + 多个字段）：强制同一目标日口径
    _other = any(k in q for k in ["数据", "来源", "哪来", "模型", "做什么", "怎么办", "措施", "保险", "损失"])
    if not _other and _asks_fields(q) and (_parse_abs_date(q) or _day_offset(q) or _horizon(q)):
        dd = day_detail(ctx, q, detail)
        if dd is not None:
            return {"text": season.clean_text(dd[0]), "chain": dd[1], "detail": detail}
    if intent in HANDLERS and HANDLERS[intent]:
        text, chains = HANDLERS[intent](ctx, q, detail)
    elif intent == "risk_today":
        cur, fc, H = ctx["cur"], ctx["fc"], ctx["H"]
        fd, off = _focus_day(ctx, q)
        if fd is not None:
            dom = []
            if fd.get("frost") or fd.get("cold_shock"):
                dom.append("霜冻/倒春寒")
            if fd.get("heat"):
                dom.append("高温")
            _dfc = fd.get("deficit") or 0
            if _dfc >= 45 or ((fd.get("dry_run") or 0) >= 5 and _dfc >= 0):
                dom.append("干旱/水分")
            if (fd.get("wet_run") or 0) >= 4:
                dom.append("连阴雨")
            lab = _dlab(off, fd["date"])
            text = f"{lab}：风险 {fd['risk_level']}（R={fd['risk_R']}，适宜度 {int(fd.get('suitability') or 0)}）。" + \
                   ("主要风险：" + "、".join(dom) + "。" if dom else "无明显主导风险。")
            if _season() == "off":
                text += " " + season.care_hint()
            if detail:
                text += " 依据：复合风险 = 倒春寒/高温/干旱 取最大；R≥0.5 记风险日。"
            return {"text": text, "chain": ["数据: Open-Meteo+集合", "风险: 专家规则R（展示值）；模型: GBDT概率(辅助)"], "detail": detail}
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
        if _season() == "off":
            text += " " + season.care_hint()
        if detail:
            text += " 依据：复合风险 = 倒春寒/高温/干旱 取最大；阈值 R≥0.5 记风险日。R 为专家规则值。"
        chains = ["数据: Open-Meteo+Meteostat", "风险: 专家规则R（展示值）；模型: GBDT概率(辅助)"]
    else:
        text, chains = fallback(ctx, q, detail)
    return {"text": season.clean_text(text), "chain": chains, "detail": detail}
