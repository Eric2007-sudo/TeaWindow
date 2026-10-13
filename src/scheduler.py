"""
新颖点：采摘调度优化（预测 → 决策/排班）。
综合"未来 7 天采摘适宜度"与"地块霜冻易感"，在每日用工产能约束下，
把 6 个地块分配到最优日期，输出可执行的采摘计划。
输出 data/processed/schedule.json
"""
import json
import os
import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
CAPACITY_PER_DAY = 2   # 每日可安排的地块数（代表用工产能）


def main():
    with open(os.path.join(PROC, "terrain.json"), encoding="utf-8") as f:
        terrain = json.load(f)
    plots = terrain["plots"]
    web = os.path.join(ROOT, "web", "data.json")
    with open(web, encoding="utf-8") as f:
        data = json.load(f)
    today = datetime.date.today().isoformat()
    fc = [d for d in data["days"] if d["source"] == "forecast" and d["date"] >= today][:7]

    # 归一化
    u = np.array([p["frost_factor"] for p in plots], dtype=float)
    u = (u - u.min()) / (u.max() - u.min() + 1e-9)          # 0..1
    suit = np.clip(np.array([d.get("suitability", 0) for d in fc]) / 100.0, 0, 1)
    risk = np.clip(np.array([d.get("risk_R", 0) for d in fc], dtype=float), 0, 1)

    unassigned = set(range(len(plots)))
    schedule = []
    for di in range(len(fc)):
        cand = []
        for pi in unassigned:
            val = suit[di] - 0.10 * di * (0.5 + u[pi]) - 0.5 * risk[di]
            cand.append((val, pi))
        cand.sort(reverse=True)
        picked = [pi for _, pi in cand[:CAPACITY_PER_DAY]]
        for pi in picked:
            unassigned.discard(pi)
        schedule.append({
            "date": fc[di]["date"],
            "risk_level": str(fc[di].get("risk_level", "")),
            "suitability": float(round(fc[di].get("suitability", 0), 0)),
            "plots": [{"name": plots[pi]["name"], "frost_risk": plots[pi]["frost_risk"],
                       "reason": ("优先抢采(霜冻易感)" if u[pi] >= 0.6 else "适宜度较优")} for pi in picked],
        })
        if not unassigned:
            break

    prio = sorted([{"name": p["name"], "frost_risk": p["frost_risk"], "urgency": round(float(u[i]), 2)}
                   for i, p in enumerate(plots)], key=lambda x: -x["urgency"])

    out = {
        "capacity_per_day": CAPACITY_PER_DAY,
        "method": "在每日产能约束下，综合采摘适宜度、延迟惩罚与地块霜冻易感，贪心分配地块到未来 7 天的最优采摘日。",
        "priority": prio,
        "days": [{"date": d["date"], "risk_level": str(d.get("risk_level", "")),
                  "suitability": float(round(d.get("suitability", 0), 0))} for d in fc],
        "schedule": schedule,
    }
    with open(os.path.join(PROC, "schedule.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 同时注入 web/data.json 与 data.js
    data["schedule"] = out
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(web, "w", encoding="utf-8") as f:
        f.write(blob)
    with open(os.path.join(ROOT, "web", "data.js"), "w", encoding="utf-8") as f:
        f.write("window.TW_DATA = " + blob + ";\n")
    for s in schedule:
        names = "、".join(p["name"] for p in s["plots"]) or "-"
        print(f"{s['date']} 适宜度{s['suitability']:.0f} 风险{s['risk_level']} -> {names}")
    print("-> data/processed/schedule.json (+注入 web/data.json)")


if __name__ == "__main__":
    main()
