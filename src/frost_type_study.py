"""霜型分层误差实验：StartLux 判霜型 → 看不同霜型下 Tmin 的误差是否不同。

真值：杭州站观测（data/processed/station_hangzhou.csv）
对比：ERA5 原始 Tmin vs 台站订正后 Tmin（daily_corrected.csv）
问题：如果辐射霜/平流霜的偏差方向不同，就可以做"按霜型分组订正"；
      分组订正必须在时间上留出（≤2022 拟合，≥2023 测试）验证。

用法：
  python src/frost_type_study.py --workers 3            # 全量 1037 天（有缓存）
  python src/frost_type_study.py --since 2022 --limit 200
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import decision_client  # noqa: E402

PROC = os.path.join(ROOT, "data", "processed")
REPORT = os.path.join(ROOT, "report")
CACHE = os.path.join(PROC, "frost_types.json")

QUESTIONS = {
    "frost_type": {
        "type": "choice",
        "instructions": "根据给定的日最低温、风速、湿度、日照与降水，判断这次低温更接近哪种类型。",
        "criteria": {
            "辐射霜": "晴空、静风（风速小）、夜间辐射降温，谷底冷池明显",
            "平流霜": "冷空气大风降温，风速较大，湿度不一定高",
            "无霜冻": "最低温明显高于霜冻阈值，或暖湿多云、风大且不冷",
        },
    }
}


def _cache_load():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _cache_save(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    json.dump(c, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE)


def classify(row, cache, retries=2):
    key = str(row["date"])[:10]
    if key in cache and cache[key].get("type"):
        return cache[key]
    state = {
        "date": key,
        "tmin": round(float(row["tmin"]), 1),
        "tmax": round(float(row["tmax"]), 1),
        "wind": round(float(row["wind"]), 1),
        "rh": round(float(row["rh"]), 0),
        "sun_hours": round(float(row["sun"]) / 3600.0, 1),
        "precip": round(float(row["precip"]), 1),
        "month": int(row["month"]),
    }
    for _ in range(retries):
        out = decision_client.try_decide(state, QUESTIONS, think_mode="never", timeout=15)
        if out:
            ans = (out.get("answers") or {}).get("frost_type") or {}
            probs = ans.get("probabilities") or {}
            label = max(probs, key=lambda k: probs[k]) if probs else None
            if label:
                rec = {"type": label, "conf": round(float(probs[label]), 3), "date": key}
                cache[key] = rec
                return rec
    cache[key] = {"type": "unknown", "conf": 0.0, "date": key}
    return cache[key]


def _mae(df, col):
    return float((df[col] - df["obs"]).abs().mean()) if len(df) else None


def _bias(df, col):
    return float((df[col] - df["obs"]).mean()) if len(df) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2015)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    d = pd.read_csv(os.path.join(PROC, "daily.csv"))
    c = pd.read_csv(os.path.join(PROC, "daily_corrected.csv"))
    s = pd.read_csv(os.path.join(PROC, "station_hangzhou.csv"))
    for x in (d, c, s):
        x["date"] = pd.to_datetime(x["date"])

    d = d.rename(columns={"temperature_2m_min": "tmin", "temperature_2m_max": "tmax",
                          "precipitation_sum": "precip", "relative_humidity_2m_mean": "rh",
                          "wind_speed_10m_max": "wind", "sunshine_duration": "sun"})
    c = c.rename(columns={"temperature_2m_min": "tmin_corr"})
    s = s.rename(columns={"tmin": "obs"})

    df = d[["date", "tmin", "tmax", "precip", "rh", "wind", "sun", "month", "year"]].merge(
        c[["date", "tmin_corr"]], on="date", how="inner").merge(
        s[["date", "obs"]], on="date", how="inner")
    df = df.dropna(subset=["tmin", "tmin_corr", "obs"])
    df = df[(df["tmin"] <= 4) & (df["year"] >= a.since)].sort_values("date").reset_index(drop=True)
    if a.limit:
        df = df.tail(a.limit).reset_index(drop=True)
    print(f"[study] 候选霜冻风险日 {len(df)}（Tmin≤4℃，{a.since}+）")

    cache = _cache_load()
    rows = [r for _, r in df.iterrows()]
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for rec in ex.map(lambda r: classify(r, cache), rows):
            done += 1
            if done % 50 == 0:
                print(f"  classified {done}/{len(rows)}")
                _cache_save(cache)
    _cache_save(cache)

    df["frost_type"] = [cache.get(str(x)[:10], {}).get("type", "unknown") for x in df["date"]]

    lines = ["# 霜型分层误差实验（StartLux 判霜型）", "",
             f"- 样本：{len(df)} 个霜冻风险日（ERA5 Tmin ≤ 4℃，{a.since}+）",
             "- 真值：杭州站观测 Tmin；对比：ERA5 原始 vs 台站订正",
             "- 目的：检验不同霜型下的偏差方向与幅度是否不同，能否做分组订正", ""]

    lines += ["## 1) 总体误差", "",
              "| 版本 | n | MAE | 偏差(均值) |", "|---|---:|---:|---:|",
              f"| ERA5 原始 | {len(df)} | {_mae(df,'tmin'):.2f} | {_bias(df,'tmin'):+.2f} |",
              f"| 台站订正 | {len(df)} | {_mae(df,'tmin_corr'):.2f} | {_bias(df,'tmin_corr'):+.2f} |", ""]

    lines += ["## 2) 分霜型", "",
              "| 霜型 | n | ERA5 MAE | ERA5 偏差 | 订正后 MAE | 订正后偏差 |",
              "|---|---:|---:|---:|---:|---:|"]
    stats = {}
    for t, g in df.groupby("frost_type"):
        stats[t] = {"n": len(g), "mae_raw": round(_mae(g, "tmin"), 2), "bias_raw": round(_bias(g, "tmin"), 2),
                    "mae_corr": round(_mae(g, "tmin_corr"), 2), "bias_corr": round(_bias(g, "tmin_corr"), 2)}
        lines.append(f"| {t} | {len(g)} | {stats[t]['mae_raw']:.2f} | {stats[t]['bias_raw']:+.2f} | "
                     f"{stats[t]['mae_corr']:.2f} | {stats[t]['bias_corr']:+.2f} |")
    lines.append("")

    # 3) 时间留出：≤2022 拟合每组偏差，≥2023 测试
    train = df[df["year"] <= 2022]
    test = df[df["year"] >= 2023].copy()
    if len(train) and len(test):
        off = {t: float((g["obs"] - g["tmin_corr"]).median()) for t, g in train.groupby("frost_type") if t != "unknown"}
        test["adj"] = test.apply(lambda r: r["tmin_corr"] + off.get(r["frost_type"], 0.0), axis=1)
        lines += ["## 3) 时间留出验证：在“已订正”基础上再加霜型偏移（≤2022 拟合，≥2023 测试）", "",
                  "| 霜型 | 偏移(℃) | 测试 n | 调整前 MAE | 调整后 MAE | 变化 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for t, g in test.groupby("frost_type"):
            before = _mae(g, "tmin_corr")
            after = float((g["adj"] - g["obs"]).abs().mean())
            lines.append(f"| {t} | {off.get(t, 0.0):+.2f} | {len(g)} | {before:.2f} | {after:.2f} | {after-before:+.2f} |")
        base = _mae(test, "tmin_corr")
        adj_all = float((test["adj"] - test["obs"]).abs().mean())
        lines += ["", f"- 整体：调整前 MAE {base:.2f} → 调整后 {adj_all:.2f}（{adj_all-base:+.2f}）", ""]
        verdict = "有分组收益，值得做分组订正" if adj_all < base - 0.02 else "无显著收益，暂不做分组订正"
        lines += [f"**结论：{verdict}。**（阈值：MAE 至少下降 0.02℃ 才考虑上线）", ""]
    else:
        lines += ["## 3) 时间留出验证", "", "样本不足，跳过。", ""]

    os.makedirs(REPORT, exist_ok=True)
    out = os.path.join(REPORT, "frost_type_study.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    json.dump({"total": len(df), "by_type": stats},
              open(os.path.join(PROC, "frost_type_stats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n".join(lines))
    print("->", out)


if __name__ == "__main__":
    main()
