"""
决策论建议 + 统一采摘口径。
- 期望效用：EV_pick/EV_protect/EV_wait（以采摘适宜度为"品质"，灾害概率为风险）。
- 统一"最佳采摘日"：best_pick_day = argmax EV_pick，并回写 data["pick_window"]（同一目标）。
读取并回写 web/data.json 的 data["decision"] 与 data["pick_window"]。
"""
import json
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import season  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

V = 100.0
LABOR = 6.0
PROTECT_COST = 4.0


def main():
    data = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
    # 季节策略：非春采期不生成采摘决策（统一业务层约束，Asia/Shanghai）
    if season.is_off():
        data["decision"] = {"season": "off", "mode": "care",
                            "task": "非春采期：以养护为主（防冻/防旱/排涝、修剪、施肥、清沟、越冬准备）",
                            "days": [], "best_pick_day": None}
        data["pick_window"] = []
        data["pick_window_note"] = "非春采期（西湖龙井 43 春采季为 3–4 月），不提供采摘窗口。"
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
        open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
        print("season=off -> 决策与采摘窗口已停用（转养护）")
        return
    today = season.iso_today()
    fc = [d for d in data["days"] if d["source"] == "forecast" and d["date"] >= today][:16]

    def haz(d):
        return max(d.get("p_frost") or 0.0, d.get("p_heat") or 0.0, (d.get("risk_R") or 0.0) * 0.6)

    def qual(d):
        return max(0.0, (d.get("suitability") or 0.0) / 100.0)

    ev_pick, ev_prot = [], []
    for d in fc:
        q, p = qual(d), haz(d)
        ev_pick.append(V * q * (1 - 0.6 * p) - LABOR)
        ev_prot.append(V * q * (1 - 0.2 * p) - LABOR - PROTECT_COST)

    days = []
    for i, d in enumerate(fc):
        ev_wait = max(ev_pick[i + 1:]) if i + 1 < len(ev_pick) else ev_pick[i]
        opts = {"抢采": ev_pick[i], "防护": ev_prot[i], "等待": ev_wait}
        act = max(opts, key=opts.get) if (d.get("suitability") or 0) >= 5 else "等待"
        days.append({"date": d["date"], "risk_level": str(d.get("risk_level", "")),
                     "p_hazard": round(haz(d), 2), "suitability": round(d.get("suitability") or 0),
                     "ev_pick": round(ev_pick[i], 1), "ev_protect": round(ev_prot[i], 1),
                     "ev_wait": round(ev_wait, 1), "recommend": act})

    order = sorted(range(len(fc)), key=lambda i: -ev_pick[i])
    best = fc[order[0]]["date"] if order else None
    window = [{"date": fc[i]["date"], "ev_pick": round(ev_pick[i], 1),
               "suitability": round(fc[i].get("suitability") or 0),
               "risk_level": str(fc[i].get("risk_level", ""))} for i in order[:5]]

    data["decision"] = {"V": V, "labor": LABOR, "protect_cost": PROTECT_COST,
                        "objective": "EV_pick = 价值×适宜度×(1-0.6×灾害概率) − 作业成本；最佳日=EV_pick 最大者",
                        "method": "以采摘适宜度为品质、集合灾害概率为风险，计算'抢采/等待/防护'期望效用并取最大。",
                        "days": days, "best_pick_day": best}
    data["pick_window"] = window
    data["pick_window_note"] = "推荐采摘窗口与'最佳采摘日'使用同一目标(期望效用)，二者一致。"
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
    open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
    print("best_pick_day:", best, "== pick_window[0]:", window[0]["date"] if window else None)
    for d in days:
        print(f"  {d['date']} 适宜度{d['suitability']} 灾害概率{d['p_hazard']} 抢采EV{d['ev_pick']} -> {d['recommend']}")


if __name__ == "__main__":
    main()
