"""
新颖点 N4：众包物候闭环——用茶农上报（+官方开采日）复校 GDD 阈值。
读取 data/processed/crowd.jsonl 中的"开采"记录，合并官方开采日，重新拟合 GDD 参数。
输出 report/recalibrate.md
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")

OFFICIAL = {2022: "2022-03-18", 2023: "2023-03-13", 2024: "2024-03-20",
            2025: "2025-03-20", 2026: "2026-03-19"}


def gdd(g, base, start_md):
    g = g.sort_values("date")
    g = g[g["date"] >= pd.Timestamp(f"{int(g['year'].iloc[0])}-{start_md}")]
    return g.assign(cum=np.maximum(0.0, g["temperature_2m_mean"] - base).cumsum())


def predict(g, base, start_md, thr):
    gg = gdd(g, base, start_md)
    gg = gg[gg["month"].isin([2, 3, 4])]
    hit = gg[gg["cum"] >= thr]
    return hit["date"].iloc[0] if len(hit) else None


def main():
    df = pd.read_csv(os.path.join(PROC, "daily.csv"))
    df["date"] = pd.to_datetime(df["date"])

    truth = dict(OFFICIAL)
    crowd = []
    cp = os.path.join(PROC, "crowd.jsonl")
    if os.path.exists(cp):
        for line in open(cp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if r.get("kind") == "开采" and r.get("date"):
                crowd.append(r)
                try:
                    y = int(str(r["date"])[:4])
                    truth[y] = str(r["date"])[:10]  # 众包优先
                except Exception:  # noqa: BLE001
                    pass

    years = [y for y in truth if y in set(df["year"])]
    best = None
    for start in ["01-01", "01-15", "02-01"]:
        for base in [6, 8, 10, 12]:
            for thr in np.arange(20, 161, 2.5):
                errs = []
                for y in years:
                    p = predict(df[df["year"] == y], base, start, float(thr))
                    errs.append(abs((pd.Timestamp(truth[y]) - p).days) if p is not None else 99)
                mae = float(np.mean(errs))
                if best is None or mae < best[0]:
                    best = (mae, start, base, float(thr))
    mae, start, base, thr = best

    md = ["# 众包物候闭环 · GDD 阈值复校\n",
          f"> 真值来源：官方开采日（{len(OFFICIAL)} 条）+ **茶农上报**（{len(crowd)} 条）。",
          f"> 复校结果：**基温 {base}℃，起算 {start}，阈值 {thr}℃·d，MAE = {mae:.1f} 天**。\n",
          "## 真值明细", "| 年份 | 开采日 | 来源 |", "|---|---|---|"]
    for y in sorted(truth):
        src = "众包" if any(int(str(c["date"])[:4]) == y for c in crowd) else "官方"
        md.append(f"| {y} | {truth[y]} | {src} |")
    md += ["\n## 闭环说明",
           "- 茶农通过 `web/report.html` 上报真实开采/灾情 → 写入 `crowd.jsonl`；",
           "- 本脚本合并官方与众包真值**复校 GDD 阈值**，实现『数据飞轮』；",
           "- 上报越多，开采期预测越准（当前众包 {} 条 → 复校后 MAE {:.1f} 天）。".format(len(crowd), mae),
           "\n> 隐私：上报去标识化，仅用于科研；见 `research/数据共享合作要点.md`。"]
    os.makedirs(REPORT, exist_ok=True)
    open(os.path.join(REPORT, "recalibrate.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))
    print("-> report/recalibrate.md")


if __name__ == "__main__":
    main()
