"""评委模拟（全场 52 个对手 + 本项目）：让 StartLux 在完整竞争场里打分。

与 judge_sim_field.py 的区别：这里把专区里去重后的 52 个作品都放进 state，
避免"只看到 6 个对手"导致的奖项概率虚高。

输出：report/judge_sim_full.md
"""
import json
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import decision_client  # noqa: E402
import judge_sim as J  # noqa: E402

FIELD = [
    ("丹橘知旱", "柑橘 10 万果农；Demo+仓库；园块→物候+四类风险+建议+问答；2022 高温提前 3 天"),
    ("CityOS", "省域台风内涝世界模型；仓库+Pages；数据许可/时效/证据类型标注完整"),
    ("CoralBleach-Agent", "珊瑚白化可核查科研流程；仓库+Demo"),
    ("微气候智能体", "茶；72h P10–P90+30m 六图层+传感器；后端 API+仓库；冷启动偶发超时"),
    ("气象翻译官", "内涝预警翻译给老人儿童；Coze 站点；研究阶段"),
    ("Zeph-AI", "区域大气/AQ 预测工作台；ModelScope；机构团队"),
    ("CoolSense", "城市微气候与高温适应平台；Pages 站点"),
    ("茶候未来", "茶；GEE 遥感+Agent 分析台；ModelScope；偏报告"),
    ("ReefTriage", "28 礁段恢复优先级；AUC 0.994+TOPSIS；Demo 仅视频"),
    ("绿风润耕", "大棚环境预测；仓库+Netlify Demo"),
    ("一垄一候", "茶；10m 静态看板；开源；无后端、无行动输出"),
    ("ThawGuard", "青藏高原热融滑塌遥感；仓库"),
    ("宁波西门防汛", "单文件 0 依赖断网可跑；576 网格巡查全序；Lift@10 3.68×"),
    ("浙镇风", "微信小程序内涝预测；无可用链接"),
    ("地球探索者", "自然语言搜卫星影像；ModelScope Demo"),
    ("RainWise", "暴雨往返风险+公告关联；仓库+线上站"),
    ("HydroFlex", "水风光互补调度；Vercel 可开"),
    ("CampusFlex", "校园光伏储能调度；Vercel 可开"),
    ("潮涌有数", "温州内涝点画像与归因；Streamlit"),
    ("甜水日历", "孟加拉淡水窗口；有仓库无 Demo"),
    ("珊海智护", "珊瑚礁管护 APP；仓库+视频"),
    ("港口风浪", "防波堤方案比选；workbench 可开"),
    ("HeatPlan", "3D 城市+UTCI+XGBoost/SHAP；仅文字"),
    ("CoastCrop", "孟加拉沿海；仓库 10KB+Streamlit"),
    ("智瞰", "气象+空气+交通多智能体；仅文字"),
    ("台风转译引擎", "预警→盖章行动清单；仅文字"),
    ("茶芽智眼", "茶；YOLOv8 识芽+积温；仓库 4.9KB；无 Demo"),
    ("山地守望", "尼泊尔多灾种通报转行动；站点 403"),
    ("BudGuard", "茶；RF POD 0.877+8 折前推+90 天计划；无 Demo"),
    ("碳索深蓝", "乐清湾蓝碳+校园碳普惠；仅文字"),
    ("海证", "核处理水排放账本；agentos 站点"),
    ("浙里雨安", "社区/校园防汛任务清单；无仓库；多版本重复"),
    ("ChronoTea", "茶；TimesFM+三带订正；无 Demo"),
    ("AIMB", "厄尔尼诺预测到研判；仅文字"),
    ("治沙选址", "西北荒漠化易发性与修复选址；仓库"),
    ("汛维", "水动力+浏览器代理模型；仅文字"),
    ("Haze Window", "新加坡烟霾出行窗口；仓库+Pages"),
    ("三江汇流", "佛山三水水生态治理提案；仅文字"),
    ("喜马拉雅滑坡", "易发性制图；仓库+论文"),
    ("塞上绿色长城", "县域治理优先级；仓库；站点连接失败"),
    ("涝有准备", "校园防汛待办工作台；仅文字"),
    ("榆见花粉", "花粉季观测与健康适应；仅文字"),
    ("飞篮计划", "仙居杨梅采运减损；仅文字"),
    ("Feed2Climate", "猪饲料精准换料降氮；仅文字"),
    ("白废待兴", "废白土做种植基质；仅文字"),
    ("Ihyaa", "土壤退化与化肥依赖；仅文字"),
    ("云贵准静止锋", "客观定线+三天预报；仅文字"),
    ("ReefAhead", "卫星数据做珊瑚巡护排班；仅文字"),
    ("旱盐智灌", "西北离线灌溉；场景未落实"),
    ("TeaWatch", "茶；35 年+官方开采日 MAE 1.8 天；静态单页；无仓库"),
    ("社区防台小助手", "地址→风险评分+72/24/6h 清单；仓库+Pages；线上超时"),
    ("Green Trace IQ", "非洲森林链锯预警；仅文字"),
]

BAND = {
    "tier": {"type": "choice", "instructions": "在这 53 个项目中，TeaWindow 综合实力处于哪一档？",
             "criteria": {"T1（前 5）": "最强档", "T2（6–15）": "强", "T3（16–30）": "中上",
                          "T4（31–53）": "中下或偏弱"}},
    "final12": {"type": "noul", "instructions": "TeaWindow 是否应进入年度 12 项（决赛）？"},
}


def _call(state, questions, label):
    for i in range(4):
        try:
            return decision_client.decide(state, questions, think_mode="auto", gate=0.9, timeout=90)
        except Exception as e:  # noqa: BLE001
            print(f"[{label}] 重试 {i+1}", repr(e)[:80], flush=True)
            time.sleep(3)
    return None


def main():
    if not decision_client.enabled():
        print("STARTLUX_API_KEY not set")
        return 1
    # 对称口径：本项目也用一行描述，避免"自家写得长 → 看起来更强"的偏差
    state = {
        "self": ("TeaWindow（梅坞采候）：茶；地块级复合风险+行动建议+问答+可打印体检卡；"
                  "1+5 护栏（数据体检+StartLux 放行/核对，fail-open）；官方开采日 MAE 1.8 天/前向 2.67 天；"
                  "开源 159 提交、155 tests；无真实用户与田间真值"),
        "field": [{"name": n, "evidence": e} for n, e in FIELD],
    }
    state["field_size"] = len(FIELD) + 1
    state["instruction"] = ("这是 AI4Climate 专区去重后的全部 53 个项目（本项目 + 52 个对手）。"
                            "请只在给定证据范围内判断，不要假设未写出的能力。")

    score_q = {k: J.QUESTIONS[k] for k in J.WEIGHTS}
    meta_q = {k: J.QUESTIONS[k] for k in ("top30", "pilot", "award")}
    meta_q.update(BAND)

    a = _call(state, score_q, "score")
    if not a:
        print("startlux unavailable")
        return 1
    ans = dict(a.get("answers") or {})
    b = _call(state, meta_q, "meta")
    if b:
        ans.update(b.get("answers") or {})

    rows, total = [], 0.0
    for k, w in J.WEIGHTS.items():
        pts = J._expected(ans.get(k) or {})
        total += pts * w
        rows.append((J.NAMES[k], w, round(pts, 1)))

    def p(k):
        return float((ans.get(k) or {}).get("noul") or 0.0)

    award_probs = (ans.get("award") or {}).get("probabilities") or {}
    band_probs = (ans.get("tier") or {}).get("probabilities") or {}
    best = max(award_probs, key=lambda x: award_probs[x]) if award_probs else "-"
    band = max(band_probs, key=lambda x: band_probs[x]) if band_probs else "-"

    lines = ["# 评委模拟（全场 52 对手 + 本项目，StartLux）", "",
             f"- 竞争场：{len(FIELD)+1} 个项目（专区去重后全部）",
             f"- 加权总分：**{total:.1f} / 100**", "",
             "| 维度 | 权重 | 分数 |", "|---|---:|---:|"]
    for name, w, pts in rows:
        lines.append(f"| {name} | {int(w*100)}% | {pts} |")
    lines += ["", "## 相对位置", "",
              f"- 最可能档位：**{band}**", "| 档位 | 概率 |", "|---|---:|"]
    for k, v in sorted(band_probs.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", f"- 进前 30：**{p('top30'):.3f}** ｜ 进决赛 12：**{p('final12'):.3f}** ｜ 90 天 pilot：**{p('pilot'):.3f}**",
              f"- 最可能奖项：**{best}**", "", "| 奖项 | 概率 |", "|---|---:|"]
    for k, v in sorted(award_probs.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {k} | {v:.3f} |")
    lines += ["", "> 模拟：模型只依据给定的一行证据；未写出的能力一律按不存在处理。"]

    os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
    out = os.path.join(ROOT, "report", "judge_sim_full.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))
    print("->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
