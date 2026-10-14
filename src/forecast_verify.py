"""
提前期预报误差评估（权威在线数据，无需等待自有快照）：
- 实况(truth)：Open-Meteo Archive（ERA5）逐日 Tmax/Tmin/降水。
- 预报(forecast)：Open-Meteo Previous Runs API（temperature_2m_previous_day{L} / precipitation_previous_day{L}，hourly→daily 聚合）。
- 对 L ∈ {1,3,7,14}：Tmin/Tmax MAE 与偏差、降水 MAE；霜冻日（Tmin≤2℃）事件级 POD/FAR/CSI/准确率。
输出：report/forecast_verify.md、report/forecast_verify.json
用法：python src\\forecast_verify.py [--days 60]
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import season  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "report")
LAT, LON = 30.2139, 120.0961
LEADS = [1, 3, 7, 14]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TeaWindow/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def truth_daily(start, end):
    u = ("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON, "start_date": start, "end_date": end, "timezone": "Asia/Shanghai",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum"}))
    d = _get(u)["daily"]
    return {day: {"tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
                  "precip": d["precipitation_sum"][i]} for i, day in enumerate(d["time"])}


def prev_run_daily(lead, start, end):
    vars_ = f"temperature_2m_previous_day{lead},precipitation_previous_day{lead}"
    u = ("https://previous-runs-api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON, "timezone": "Asia/Shanghai", "past_days": 92, "forecast_days": 1,
        "hourly": vars_}))
    h = _get(u)["hourly"]
    tkey = f"temperature_2m_previous_day{lead}"
    pkey = f"precipitation_previous_day{lead}"
    if tkey not in h:
        return {}
    byday = {}
    for i, t in enumerate(h["time"]):
        day = t[:10]
        if day < start or day > end:
            continue
        b = byday.setdefault(day, {"tmin": 1e9, "tmax": -1e9, "precip": 0.0})
        tv = h[tkey][i]
        if tv is not None:
            b["tmin"] = min(b["tmin"], tv); b["tmax"] = max(b["tmax"], tv)
        if pkey in h and h[pkey][i] is not None:
            b["precip"] += h[pkey][i] or 0.0
    for day in list(byday):
        if byday[day]["tmin"] > 1e8:
            del byday[day]
    return byday


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    end = (season.today() - __import__("datetime").timedelta(days=1)).isoformat()
    start = (season.today() - __import__("datetime").timedelta(days=a.days)).isoformat()
    print(f"窗口 {start} ~ {end}")
    truth = truth_daily(start, end)
    rows = []
    for L in LEADS:
        try:
            fc = prev_run_daily(L, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"L={L} 抓取失败: {e}")
            continue
        common = sorted(set(truth) & set(fc))
        if len(common) < 5:
            print(f"L={L} 样本不足({len(common)})，跳过")
            continue
        tt = np.array([truth[d]["tmin"] for d in common]); ft = np.array([fc[d]["tmin"] for d in common])
        tx = np.array([truth[d]["tmax"] for d in common]); fx = np.array([fc[d]["tmax"] for d in common])
        tp = np.array([truth[d]["precip"] or 0 for d in common]); fp = np.array([fc[d]["precip"] or 0 for d in common])
        fev = ft <= 2; tev = tt <= 2
        tp_ = int((fev & tev).sum()); fp_ = int((fev & ~tev).sum()); fn_ = int((~fev & tev).sum()); tn_ = int((~fev & ~tev).sum())
        pod = tp_ / (tp_ + fn_) if (tp_ + fn_) else None
        far = fp_ / (tp_ + fp_) if (tp_ + fp_) else None
        csi = tp_ / (tp_ + fp_ + fn_) if (tp_ + fp_ + fn_) else None
        acc = (tp_ + tn_) / max(1, len(common))
        rows.append({"lead": L, "n": len(common),
                     "tmin_mae": round(float(np.mean(np.abs(ft - tt))), 2),
                     "tmin_bias": round(float(np.mean(ft - tt)), 2),
                     "tmax_mae": round(float(np.mean(np.abs(fx - tx))), 2),
                     "tmax_bias": round(float(np.mean(fx - tx)), 2),
                     "precip_mae": round(float(np.mean(np.abs(fp - tp))), 2),
                     "frost_tp": tp_, "frost_fp": fp_, "frost_fn": fn_, "frost_tn": tn_,
                     "pod": None if pod is None else round(pod, 3),
                     "far": None if far is None else round(far, 3),
                     "csi": None if csi is None else round(csi, 3),
                     "acc": round(acc, 3)})
    out = {"site": "梅家坞", "lat": LAT, "lon": LON, "window": [start, end],
           "truth": "Open-Meteo Archive (ERA5)", "forecast": "Open-Meteo Previous Runs",
           "generated": season.now().isoformat(timespec="seconds"), "leads": rows}
    os.makedirs(REPORT, exist_ok=True)
    json.dump(out, open(os.path.join(REPORT, "forecast_verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    md = ["# 提前期预报误差（权威在线数据）\n",
          f"> 站点：梅家坞（{LAT}N,{LON}E）｜窗口：{start} ~ {end}｜生成：{out['generated']}",
          f"> 实况：{out['truth']}；预报：{out['forecast']}（previous_day{{L}}）。\n",
          "## 温度/降水误差（MAE=平均绝对误差，bias=预报−实况）",
          "| 提前期 | 样本 | Tmin MAE | Tmin bias | Tmax MAE | Tmax bias | 降水 MAE(mm) |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['lead']}天 | {r['n']} | {r['tmin_mae']} | {r['tmin_bias']} | {r['tmax_mae']} | {r['tmax_bias']} | {r['precip_mae']} |")
    md += ["", "## 霜冻日事件级（阈值 Tmin≤2℃）",
           "| 提前期 | TP | FP | FN | TN | POD(命中率) | FAR(空报率) | CSI | 准确率 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['lead']}天 | {r['frost_tp']} | {r['frost_fp']} | {r['frost_fn']} | {r['frost_tn']} | "
                  f"{r['pod']} | {r['far']} | {r['csi']} | {r['acc']} |")
    md += ["", "> 说明：这是**权威在线归档**（Previous Runs vs ERA5）的真实提前期误差，**不依赖自有快照**；",
           "> 自有每日快照仍会随刷新累积（`/api/data/versions`），用于长期核对与发布完整性。"]
    open(os.path.join(REPORT, "forecast_verify.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))
    print("-> report/forecast_verify.{md,json}")


if __name__ == "__main__":
    main()