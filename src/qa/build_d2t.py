"""
M2 合成"数据到文本(D2T)"训练集：给定【问题 + 结构化事实】→【自然简洁回答】。
用多变体措辞库生成，供 GPU 微调小型生成模型（Qwen2.5-0.5B）时学习自然表达。
输出 data/qa/d2t/{train,eval}.jsonl（chat 格式）
"""
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "qa", "d2t")
rng = random.Random(7)

SYS = ("你是梅坞采候 TeaWindow 的茶农助手。只依据给定事实作答，先给结论，再给1–2条可执行动作，"
       "简洁口语化（≤120字），涉及数值要用事实里的数字，不编造。")


def qbank():
    return {
        "frost": ["要不要防冻", "会不会倒春寒", "未来几天有霜冻吗", "要不要防冻保护", "会打霜吗"],
        "heat": ["要不要遮阳", "会不会高温", "要不要防高温", "会有热害吗"],
        "drought": ["要不要浇水", "要不要灌溉", "干旱严重吗", "土壤干不干"],
        "rain": ["要不要排水", "连阴雨影响大吗", "要不要防涝"],
        "pick_window": ["今天适合采茶吗", "什么时候采最好", "采摘窗口怎么样"],
        "schedule": ["先采哪块地", "怎么安排采摘", "明天采哪块"],
        "decision": ["要不要抢采", "该抢采还是等", "今天采还是等"],
        "risk_today": ["今天有风险吗", "现在风险大不大", "有没有预警"],
        "plot": ["哪块地风险高", "坡上更怕冻吗"],
        "insurance": ["保险多少钱一亩", "怎么理赔", "保费多少"],
        "value": ["预计损失多少", "值多少钱", "能省多少"],
        "harvest_date": ["今年什么时候开采", "开采期预测", "什么时候上市"],
        "model": ["你们用什么模型", "准不准", "怎么训练的"],
        "data_source": ["数据哪来的", "用什么数据"],
        "greet": ["你好", "谢谢"],
    }


# 每个意图：给出 (facts生成器, answer 变体生成器)
PLOTS = ["梅家坞村口", "梅坞溪谷", "北坡茶园", "山坡中段", "高处茶园", "云栖方向"]


def f_frost():
    H = rng.choice([7, 15, 30])
    tmin = round(rng.uniform(-2, 14), 1)
    dmin = f"2026-{rng.choice(['10','11','03'])}-{rng.randint(1,28):02d}"
    need = tmin <= 2 or (H > 16 and rng.random() < .3)
    return {"H": H, "minTmin": tmin, "minTmin_date": dmin, "frost_prob": round(max(0, (4 - tmin) / 6), 2),
            "clim_frost_prob": round(rng.uniform(0, .6), 2)}, need


def a_frost(f, need):
    lead = rng.choice(["不用防冻。", "目前无需防冻。", "这几天不用防冻。"]) if not need else \
        rng.choice(["要防冻。", "建议提前防冻。", "需重点防冻。"])
    if not need:
        body = rng.choice([
            f"未来{f['H']}天最低温{f['minTmin']}℃（{f['minTmin_date']}），无霜冻风险，正常采即可。",
            f"预报期内最低{f['minTmin']}℃，不达霜冻线，按常规管理。",
        ])
    else:
        body = rng.choice([
            f"{f['minTmin_date']}前后可能下霜，最低{f['minTmin']}℃（概率{f['frost_prob']}）。夜晨覆盖/熏烟，达标芽先抢采。",
            f"有霜冻风险：{f['minTmin_date']}最低{f['minTmin']}℃，建议覆盖保温并优先抢采。",
        ])
    if f["H"] > 16:
        body += f" 更长看气候：同期霜冻日概率约{int(f['clim_frost_prob']*100)}%。"
    return lead + body


def f_heat():
    H = rng.choice([7, 15]); tmax = round(rng.uniform(24, 39), 1)
    return {"H": H, "maxTmax": tmax, "heat_prob": round(max(0, (tmax - 33) / 8), 2)}, tmax >= 33


def a_heat(f, need):
    if not need:
        return rng.choice([f"不用遮阳，未来{f['H']}天最高{f['maxTmax']}℃，无高温风险。",
                           f"暂不用防高温，最高{f['maxTmax']}℃。"])
    return rng.choice([f"建议遮阳：最高{f['maxTmax']}℃（概率{f['heat_prob']}），上遮阳网、傍晚浇透水。",
                       f"注意高温，{f['maxTmax']}℃易灼伤，遮阴并补水。"])


def f_drought():
    dry = rng.randint(0, 15); deficit = round(rng.uniform(-40, 80), 0); soil = round(rng.uniform(.12, .45), 2)
    need = dry >= 5 or deficit >= 45 or soil < .25
    return {"dry_run": dry, "deficit": deficit, "soil": soil}, need


def a_drought(f, need):
    if not need:
        return rng.choice([f"暂不用灌溉，连旱{f['dry_run']}天、亏缺{f['deficit']}，水分尚可。",
                           f"不用急着浇水，土壤水分还行。"])
    return rng.choice([f"建议灌溉：连旱{f['dry_run']}天、亏缺{f['deficit']}，早晚浇透并覆盖保墒，优先幼树。",
                       f"该补水了，连续少雨，浇一次跑马水，别中午猛灌。"])


def f_rain():
    wet = rng.randint(0, 10); rain = rng.randint(0, 60)
    return {"wet_run": wet, "rain_next": rain}, (wet >= 4 or rain >= 25)


def a_rain(f, need):
    if not need:
        return f"不用特别防雨，连雨{f['wet_run']}天、未来降水约{f['rain_next']}mm。"
    return rng.choice([f"注意排水：连雨{f['wet_run']}天、未来约{f['rain_next']}mm，清沟防沤根，鲜叶及时摊青。",
                       f"要防连阴雨，低洼地清沟排水，鲜叶别闷堆。"])


def f_pick():
    suit = rng.randint(0, 100); best = f"2026-10-{rng.randint(12,27):02d}"
    return {"suitability": suit, "best_day": best}, suit >= 40


def a_pick(f, need):
    lead = "今天适合采。" if need else "今天不太适合采。"
    return lead + f" 今日适宜度{f['suitability']}，推荐最佳采摘日{f['best_day']}。"


def f_sched():
    first = rng.sample(PLOTS, 2)
    return {"first": first, "date": f"2026-10-{rng.randint(12,20):02d}"}, True


def a_sched(f, need):
    return rng.choice(["建议先采：", "优先采：", "第一优先："]) + f"{'、'.join(f['first'])}（{f['date']}）。"


def f_dec():
    rec = rng.choice(["抢采", "等待", "防护"]); p = round(rng.uniform(0, .6), 2)
    return {"recommend": rec, "p_hazard": p, "best_day": f"2026-10-{rng.randint(12,20):02d}"}, True


def a_dec(f, need):
    return f"建议{f['recommend']}。今日灾害概率{f['p_hazard']}，最佳采摘日{f['best_day']}。"


def f_risk():
    lv = rng.choice(["低", "中", "高"]); R = round(rng.uniform(0, 1), 2)
    return {"date": "2026-10-13", "level": lv, "R": R, "suitability": rng.randint(0, 90)}, True


def a_risk(f, need):
    return f"总体风险{f['level']}。{f['date']} 风险{f['level']}（R={f['R']}），适宜度{f['suitability']}。"


def f_plot():
    high = rng.sample(PLOTS, rng.randint(1, 3))
    return {"high": high, "n": 6}, True


def a_plot(f, need):
    return f"最需关注（霜冻易感高）：{'、'.join(f['high'])}。北坡/低洼更易受冻，优先防冻抢采。"


def f_ins():
    return {"frost_th": rng.choice([120, 134, 150]), "pay": rng.choice([1000, 1600]),
            "fire": rng.randint(3, 9), "n": 12, "fair": rng.choice([600, 800, 1000])}, True


def a_ins(f, need):
    return f"指数保险：霜冻阈值{f['frost_th']}度日、赔付{f['pay']}元/亩；历史赔付{f['fire']}/{f['n']}年，公平保费≈{f['fair']}元/亩，按客观指数自动理赔。"


def f_val():
    v = rng.choice([12000, 16000, 20000]); loss = rng.choice([2400, 3200, 4000])
    return {"value": v, "loss": loss, "prem": 10, "benefit": round(loss * .2)}, True


def a_val(f, need):
    return f"示意测算：亩产值约{f['value']}元，期望损失≈{f['loss']}元/亩·年，参考保费{f['prem']}元/亩，工具减损≈{f['benefit']}元/亩·年。"


def f_harv():
    d = rng.choice(["2026-03-16", "2026-03-19", "2026-03-20"]); mae = round(rng.uniform(1, 3), 1)
    return {"pred": d, "mae": mae}, True


def a_harv(f, need):
    return f"今年开采日预测约{f['pred']}（对官方开采日 MAE≈{f['mae']}天）。"


def f_model():
    return {}, True


def a_model(f, need):
    return rng.choice([
        "本问答为自研引擎：自训意图分类+接地生成，核心为纯 numpy GBDT 复合风险(AUC 0.998)。",
        "用我们自己训练的模型：GBDT 复合风险 + 概率校准 + 集合不确定性，非调用大模型检索。",
    ])


def f_data():
    return {}, True


def a_data(f, need):
    return "数据来自公开源：Open-Meteo(气象)、Meteostat(台站)、NASA GIBS/Sentinel-2(遥感)、DEM(地形)。"


def f_greet():
    return {}, True


def a_greet(f, need):
    return rng.choice(["你好！可以问今天风险、要不要防冻/灌溉、采哪块地、保险与损失等。",
                       "您好，我是梅坞采候助手，随时为您看风险与采摘建议。"])


SPEC = {
    "frost": (f_frost, a_frost), "heat": (f_heat, a_heat), "drought": (f_drought, a_drought),
    "rain": (f_rain, a_rain), "pick_window": (f_pick, a_pick), "schedule": (f_sched, a_sched),
    "decision": (f_dec, a_dec), "risk_today": (f_risk, a_risk), "plot": (f_plot, a_plot),
    "insurance": (f_ins, a_ins), "value": (f_val, a_val), "harvest_date": (f_harv, a_harv),
    "model": (f_model, a_model), "data_source": (f_data, a_data), "greet": (f_greet, a_greet),
}


def main():
    os.makedirs(OUT, exist_ok=True)
    qb = qbank()
    samples = []
    for _ in range(3600):
        it = rng.choice(list(SPEC.keys()))
        fgen, agen = SPEC[it]
        facts, need = fgen()
        q = rng.choice(qb[it])
        ans = agen(facts, need)
        user = f"问题：{q}\n事实：{json.dumps(facts, ensure_ascii=False)}"
        samples.append({"messages": [{"role": "system", "content": SYS},
                                     {"role": "user", "content": user},
                                     {"role": "assistant", "content": ans}]})
    rng.shuffle(samples)
    n = len(samples); cut = int(n * 0.9)
    with open(os.path.join(OUT, "train.jsonl"), "w", encoding="utf-8") as f:
        for s in samples[:cut]:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "eval.jsonl"), "w", encoding="utf-8") as f:
        for s in samples[cut:]:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"D2T 样本: train={cut} eval={n-cut} -> data/qa/d2t/")


if __name__ == "__main__":
    main()
