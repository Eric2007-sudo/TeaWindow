"""
逐月气候概率：为"超出预报期(>16天)"的风险问题提供历史气候基线。
计算每个自然月的：霜冻日概率、倒春寒日概率、Tmin 均值/最低。
注入 web/data.json 的 data["climatology"]。
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
WEB = os.path.join(ROOT, "web")


def main():
    df = pd.read_csv(os.path.join(PROC, "predictions.csv"))
    df["date"] = pd.to_datetime(df["date"])
    rows = []
    for m in range(1, 13):
        g = df[df["date"].dt.month == m]
        if len(g) == 0:
            continue
        rows.append({
            "month": m,
            "frost_day_prob": round(float(g["frost"].mean()), 3),
            "cold_shock_day_prob": round(float(g["cold_shock"].mean()), 3),
            "heat_day_prob": round(float(g["heat"].mean()), 3),
            "tmin_mean": round(float(g["temperature_2m_min"].mean()), 1),
            "tmin_min": round(float(g["temperature_2m_min"].min()), 1),
        })
    clim = {"monthly": rows, "note": "基于 2015–2026 的历史气候概率（用于超出 16 天预报期的风险参考）。"}
    p = os.path.join(WEB, "data.json")
    d = json.load(open(p, encoding="utf-8"))
    d["climatology"] = clim
    blob = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    open(p, "w", encoding="utf-8").write(blob)
    open(os.path.join(WEB, "data.js"), "w", encoding="utf-8").write("window.TW_DATA = " + blob + ";\n")
    for r in rows:
        print(f"{r['month']:2d}月 霜冻日概率 {r['frost_day_prob']:.2f} 倒春寒 {r['cold_shock_day_prob']:.2f} "
              f"Tmin均值 {r['tmin_mean']} 最低 {r['tmin_min']}")
    print("-> 注入 web/data.json 的 climatology")


if __name__ == "__main__":
    main()
