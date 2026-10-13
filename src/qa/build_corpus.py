"""
A-1 语料构建：合成"茶农口吻"问答意图标注集（用于训练我们自己的意图分类器）。
- 结合本项目场景与公开报道/访谈的常见问法，合理外延。
输出 data/qa/intents_train.jsonl、data/qa/intents_eval.jsonl、data/qa/knowledge.json
"""
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QA = os.path.join(ROOT, "data", "qa")

# 意图 -> 茶农口吻样例（每类 ≥ 14 条）
INTENTS = {
    "risk_today": [
        "今天茶园有风险吗", "现在有没有什么风险", "今天整体天气对茶树有影响不",
        "这两天茶园安全吗", "现在风险大不大", "今天要不要注意点啥", "有没有灾害预警",
        "最近天气对春茶影响大吗", "这几天茶山上有啥隐患", "今天适合上山干活吗",
        "当前茶园状况怎么样", "有没有需要防范的天气", "现在茶树有没有危险",
    ],
    "frost": [
        "最近会倒春寒吗", "会不会下霜冻到茶芽", "明天早上有霜冻吗", "这几天会不会打霜",
        "春茶会不会被冻坏", "倒春寒来了没有", "夜里温度会不会太低冻伤嫩芽",
        "有霜冻风险要不要防冻", "今年会不会有倒春寒", "低温会不会影响明前茶",
        "什么时候要防霜冻", "冻害风险大不大", "茶芽会不会被冻焦",
    ],
    "heat": [
        "高温会不会晒伤茶树", "这几天会不会太热", "夏天茶树怎么防高温", "会不会有热害",
        "高温干旱严重吗", "大中午的要不要遮阳", "会不会被晒焦", "最近会不会有连续高温",
        "伏旱来了吗", "高温对来年春茶有影响吗", "要不要拉遮阳网", "天太热茶树顶会不会灼伤",
        "热害风险高不高",
    ],
    "drought": [
        "多久没下雨了要不要浇水", "土壤干不干要不要灌溉", "干旱风险大不大",
        "茶园缺水吗", "要不要给幼树补水", "几天没下雨了", "水分亏缺严重吗",
        "是不是该灌溉了", "旱情怎么样", "要不要浇透水", "土壤墒情如何",
        "连续晴热要不要灌水", "干旱会不会影响发芽",
    ],
    "rain": [
        "下雨要不要采茶", "连阴雨对采摘有影响吗", "雨水多了怎么办", "要不要清沟排水",
        "土壤太湿会不会沤根", "连续下雨茶树会不会烂根", "雨天鲜叶怎么处理",
        "降水多品质会不会变差", "要不要防涝", "这几天雨大不大", "湿害风险大吗",
        "下雨天能不能采",
    ],
    "pick_window": [
        "什么时候采明前茶最好", "明天适合采茶吗", "这几天采摘窗口怎么样",
        "今天适合采茶吗", "明前还是雨前采好", "采摘适宜度高不高", "什么时候开采合适",
        "这两天能采茶吗", "今年的采摘期怎么样", "现在采还是过两天采",
        "采摘的最佳日子是哪天", "春茶什么时候采品质最好",
    ],
    "schedule": [
        "先采哪块地", "明天安排采哪片茶园", "帮我排一下采摘计划", "哪块地该先抢采",
        "地块太多先采哪个", "怎么安排采茶队", "哪片茶园优先采", "未来一周怎么排采摘",
        "哪块地风险高要先采", "帮我排个采茶排班", "明天上山采哪块", "按什么顺序采摘",
    ],
    "decision": [
        "该抢采还是再等等", "要不要现在抢采", "今天采还是等两天", "要不要提前采掉",
        "风险和品质怎么权衡", "是抢采还是防护", "要不要抢在霜冻前采", "值不值得今天采",
        "该不该冒险采", "现在动手还是观察", "建议抢采吗", "要不要提前采摘规避风险",
    ],
    "insurance": [
        "茶叶保险怎么买", "保费多少钱一亩", "受灾能赔多少", "有没有天气指数保险",
        "保险划算吗", "保额多少", "怎么理赔", "指数保险是怎么赔的", "一亩地保费多少",
        "霜冻能赔钱吗", "保险赔付怎么算", "要不要买茶叶保险",
    ],
    "value": [
        "这风险值多少钱", "预计会损失多少", "一年损失大概多少", "防灾能省多少钱",
        "投入值不值", "损失大吗", "这工具能帮我省多少钱", "每亩预期损失多少",
        "防护能挽回多少损失", "风险的经济影响大不大", "值不值得用这个系统",
        "一年能减少多少损失",
    ],
    "harvest_date": [
        "今年西湖龙井什么时候开采", "开采期大概几号", "今年茶什么时候能采",
        "今年的开采日期定了吗", "什么时候正式开采", "明前茶什么时候上市",
        "今年开采会不会提前", "开采期预测是多少", "茶叶什么时候发芽开采",
        "今年头采是哪天", "开采时间比去年早还是晚",
    ],
    "data_source": [
        "你们的数据从哪来的", "用的什么数据", "数据可靠吗", "气象数据哪里来的",
        "遥感数据是什么", "台站数据从哪拿的", "数据来源是什么", "有没有用卫星数据",
        "这些指标怎么算出来的", "数据多久更新一次", "数据是公开的吗",
    ],
    "model": [
        "你们用什么模型", "AI是怎么预测的", "模型准不准", "准确率多少",
        "预测靠不靠谱", "模型怎么训练的", "这是不是调用大模型", "为什么用机器学习",
        "模型的依据是什么", "怎么保证不误报", "模型会不会出错", "有没有独立验证",
        "这个AI是你们自己做的吗",
    ],
    "plot": [
        "哪块地风险最高", "不同地块有啥区别", "我的地块和别人的一样吗",
        "坡上的茶园风险大吗", "低洼地是不是更容易冻", "哪片茶园最容易受冻",
        "地块之间差别大吗", "北坡的茶园要注意啥", "地形对风险有影响吗",
        "哪块地更怕霜冻", "不同海拔有区别吗",
    ],
    "greet": [
        "你好", "在吗", "谢谢", "你好呀", "帮我看看", "你好，问个问题", "谢谢啦",
        "辛苦了", "早上好", "有人吗",
    ],
}

# 知识/事实（供检索与接地回答；均来自本项目产出）
KNOWLEDGE = {
    "data_sources": [
        "气象：Open-Meteo(ERA5 再分析 2015 至今 + 16 天预报)",
        "台站观测：Meteostat 杭州站 WMO 58457（逐日观测，用于交叉验证与偏差订正）",
        "遥感：NASA GIBS MODIS NDVI（颜色近似反演）+ Sentinel-2 L2A 数值 NDVI",
        "地形：Open-Meteo Elevation（90m，海拔/坡度/坡向）",
        "集合预报：Open-Meteo Ensemble（GFS/ECMWF/ICON，约 122 成员）",
        "物候真值：官方公布的历年西湖龙井开采日",
    ],
    "model": [
        "核心模型：纯 numpy 梯度提升树(GBDT) 识别复合风险（倒春寒×高温×干旱）",
        "训练 2015–2023，测试 2024–2025：AUC 0.998 / F1 0.854；单阈值基线 AUC 0.78",
        "三模型对照：单阈值 0.78 < 逻辑回归 0.968 < GBDT 0.998",
        "概率校准(Platt)：Brier 0.021→0.012；AUC 95%CI ≈ [0.996,0.999]",
        "物候：GDD 开采期预测 MAE≈1.8 天（对官方开采日）",
        "不确定性：集合预报给出 P(霜冻)/P(高温) 概率",
    ],
    "qa_engine": [
        "本问答为自研引擎：意图分类+检索+接地生成，答案来自本项目数据与模型，而非调用大模型检索",
    ],
}


def main():
    os.makedirs(QA, exist_ok=True)
    rng = random.Random(42)
    train, ev = [], []
    for intent, qs in INTENTS.items():
        for q in qs:
            rec = {"text": q, "intent": intent}
            (ev if rng.random() < 0.2 else train).append(rec)
    # 增广：同义替换 + 称呼/语气前后缀 + 轻度字符噪声
    prefixes = ["", "师傅，", "请问", "想问问，", "帮我看下，", "麻烦问下，", "请教下，", "老板，"]
    suffixes = ["", "呢", "吗", "啊", "？", "呀", "，谢谢"]
    syn = {"霜冻": ["下霜", "打霜", "冻害"], "高温": ["大热天", "酷热", "热害"], "采摘": ["采茶", "开采", "摘茶"],
           "地块": ["茶园", "地", "山场"], "灌溉": ["浇水", "灌水"], "保险": ["保费", "投保"],
           "损失": ["亏", "赔", "亏本"], "寒潮": ["冷空气", "倒春寒"]}

    def augment(text):
        t = text
        for k, vs in syn.items():
            if k in t and rng.random() < 0.5:
                t = t.replace(k, rng.choice(vs))
        t = rng.choice(prefixes) + t + rng.choice(suffixes)
        if rng.random() < 0.35 and len(t) > 4:
            i = rng.randrange(len(t)); t = t[:i] + t[i + 1:]
        return t

    aug = []
    for rec in list(train):
        for _ in range(6):
            aug.append({"text": augment(rec["text"]), "intent": rec["intent"]})
    train += aug
    rng.shuffle(train); rng.shuffle(ev)
    with open(os.path.join(QA, "intents_train.jsonl"), "w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(QA, "intents_eval.jsonl"), "w", encoding="utf-8") as f:
        for r in ev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(QA, "knowledge.json"), "w", encoding="utf-8") as f:
        json.dump(KNOWLEDGE, f, ensure_ascii=False, indent=2)

    # 蒸馏用：生成大量合成问句（无标签），供 GPU-BERT 打伪标签
    allqs = [q for qs in INTENTS.values() for q in qs]
    with open(os.path.join(QA, "pseudo_input.jsonl"), "w", encoding="utf-8") as f:
        for _ in range(4000):
            f.write(json.dumps({"text": augment(rng.choice(allqs))}, ensure_ascii=False) + "\n")

    print(f"意图数={len(INTENTS)} 训练={len(train)} 评测={len(ev)}")
    print("-> data/qa/intents_train.jsonl, intents_eval.jsonl, knowledge.json, pseudo_input.jsonl")


if __name__ == "__main__":
    main()
