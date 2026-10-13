"""
新颖点 N1：决策论建议（不确定性驱动）。
用集合预报的灾害概率，对"抢采 / 等待 / 防护"计算期望效用，给出每日推荐动作。
读取 web/data.json，注入 data["decision"]。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

V = 100.0          # 一次理想采摘的相对价值
LABOR = 6.0        # 采摘作业成本(相对)
PROTECT_COST = 4.0 # 防护投入成本(相对)
QUALITY_PER_DAY = 0.04  # 每延迟一天的品质/鲜爽损失


def main():
    data = json.load(open(os.path.join(WEB, "data.json"), encoding="utf-8"))
    fc = [d for d in data["days"] if d["source"] == "forecast"][:7]

    def haz(d):
        pf = d.get("p_frost") or 0.0
        ph = d.get("p_heat") or 0.0
        rr = d.get("risk_R") or 0.0
        return max(pf, ph, rr * 0.6)  # 综合灾害概率（保守混合）

    ev_pick, ev_prot = [], []
    for di, d in enumerate(fc):
        q = max(0.0, 1 - QUALITY_PER_DAY * di)
        p = haz(d)
        ev_pick.append(V * q * (1 - 0.6 * p) - LABOR)
        ev_prot.append(V * q * (1 - 0.2 * p) - LABOR - PROTECT_COST)

    days = []
    for di, d in enumerate(fc):
        future = ev_pick[di + 1:] or [ev_pick[di]]
        ev_wait = max(future)
        opts = {"抢采": ev_pick[di], "防护": ev_prot[di], "等待": ev_wait}
        act = max(opts, key=opts.get)
        days.append({"date": d["date"], "risk_level": str(d.get("risk_level", "")),
                     "p_hazard": round(haz(d), 2),
                     "ev_pick": round(ev_pick[di], 1), "ev_protect": round(ev_prot[di], 1),
                     "ev_wait": round(ev_wait, 1), "recommend": act})

    best_i = int(max(range(len(fc)), key=lambda i: ev_pick[i])) if fc else None
    out = {"V": V, "labor": LABOR, "protect_cost": PROTECT_COST, "quality_per_day": QUALITY_PER_DAY,
           "method": "用集合灾害概率对'抢采/等待/防护'计算期望效用并取最大；延迟按日损失品质。",
           "days": days,
           "best_pick_day": (fc[best_i]["date"] if best_i is not None else None)}
    data["decision"] = out
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(WEB, "data.json"), "w", encoding="utf-8").write(blob)
    open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
    for d in days:
        print(f"{d['date']} 灾害概率{d['p_hazard']} 抢采EV{d['ev_pick']} 防护EV{d['ev_protect']} 等待EV{d['ev_wait']} -> {d['recommend']}")
    print("最佳采摘日:", out["best_pick_day"], "-> 注入 web/data.json")


if __name__ == "__main__":
    main()
