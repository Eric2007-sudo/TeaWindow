"""
权威在线预报验证（两轨）：
A) 提前期误差（1/3/7 天）：Open-Meteo Previous Runs vs ERA5 实况（近窗口）。
B) 多年春采季霜冻（2–4 月）：Open-Meteo Historical Forecast 归档 vs ERA5 实况，
   给出逐年与汇总 Tmin/Tmax/降水 MAE、霜冻日事件级 POD/FAR/CSI、bootstrap 95% 置信区间与基线对照。
输出：report/forecast_verify.md、report/forecast_verify.json
用法：python src\\forecast_verify.py [--days 60] [--years 2022,2023,2024,2025]
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
LEADS = [1, 3, 7]
FROST_TH = 2.0


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


def histfc_daily(start, end):
    u = ("https://historical-forecast-api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
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
    tkey, pkey = f"temperature_2m_previous_day{lead}", f"precipitation_previous_day{lead}"
    if tkey not in h:
        return {}
    byday = {}
    for i, t in enumerate(h["time"]):
        day = t[:10]
        if day < start or day > end:
            continue
        b = byday.setdefault(day, {"tmin": 1e9, "tmax": -1e9, "precip": 0.0})
        if h[tkey][i] is not None:
            b["tmin"] = min(b["tmin"], h[tkey][i]); b["tmax"] = max(b["tmax"], h[tkey][i])
        if pkey in h and h[pkey][i] is not None:
            b["precip"] += h[pkey][i] or 0.0
    return {d: v for d, v in byday.items() if v["tmin"] < 1e8}


def boot_ci(x, n=1000, seed=0):
    x = np.asarray([v for v in x if v is not None], dtype=float)
    if len(x) < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    ms = [float(np.mean(rng.choice(x, size=len(x), replace=True))) for _ in range(n)]
    return (round(float(np.percentile(ms, 2.5)), 2), round(float(np.percentile(ms, 97.5)), 2))


def finite(a):
    return [v for v in a if v is not None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--years", default="2022,2023,2024,2025")
    a = ap.parse_args()
    import datetime
    end = (season.today() - datetime.timedelta(days=1)).isoformat()
    start = (season.today() - datetime.timedelta(days=a.days)).isoformat()
    out = {"site": "梅家坞", "lat": LAT, "lon": LON, "generated": season.now().isoformat(timespec="seconds"),
           "truth": "Open-Meteo Archive (ERA5)"}

    # ---------- A) 提前期 ----------
    truth = truth_daily(start, end)
    leads = []
    for L in LEADS:
        try:
            fc = prev_run_daily(L, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"L={L} 抓取失败: {e}"); continue
        common = sorted(set(truth) & set(fc))
        if len(common) < 5:
            continue
        tt = np.array(finite([truth[d]["tmin"] for d in common]))
        ft = np.array(finite([fc[d]["tmin"] for d in common]))
        tx = np.array(finite([truth[d]["tmax"] for d in common]))
        fx = np.array(finite([fc[d]["tmax"] for d in common]))
        err = np.abs(ft - tt)
        lo, hi = boot_ci(err)
        fev = ft <= FROST_TH; tev = tt <= FROST_TH
        tp, fp, fn, tn = int((fev & tev).sum()), int((fev & ~tev).sum()), int((~fev & tev).sum()), int((~fev & ~tev).sum())
        leads.append({"lead": L, "n": len(common),
                      "tmin_mae": round(float(np.mean(err)), 2), "tmin_mae_ci95": [lo, hi],
                      "tmin_bias": round(float(np.mean(ft - tt)), 2),
                      "tmax_mae": round(float(np.mean(np.abs(fx - tx))), 2),
                      "precip_mae": round(float(np.mean(np.abs(np.array(finite([fc[d]["precip"] or 0 for d in common])) -
                                                             np.array(finite([truth[d]["precip"] or 0 for d in common]))))), 2),
                      "frost_tp": tp, "frost_fp": fp, "frost_fn": fn, "frost_tn": tn,
                      "pod": round(tp / (tp + fn), 3) if (tp + fn) else None,
                      "far": round(fp / (tp + fp), 3) if (tp + fp) else None,
                      "csi": round(tp / (tp + fp + fn), 3) if (tp + fp + fn) else None})
    out["leads"] = leads
    out["lead_window"] = [start, end]

    # ---------- B) 多年春采季霜冻 ----------
    years = [int(y) for y in a.years.split(",") if y.strip()]
    per_year = []
    pooled_err = []
    pooled_bias = []
    pooled_persist = []
    pooled = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for y in years:
        s, e = f"{y}-02-01", f"{y}-04-30"
        try:
            tr = truth_daily(s, e); pr = histfc_daily(s, e)
        except Exception as ex:  # noqa: BLE001
            print(f"{y} 抓取失败: {ex}"); continue
        common = [d for d in sorted(set(tr) & set(pr)) if tr[d]["tmin"] is not None and pr[d]["tmin"] is not None]
        if len(common) < 20:
            print(f"{y} 样本不足({len(common)})，跳过"); continue
        tt = np.array([tr[d]["tmin"] for d in common]); ft = np.array([pr[d]["tmin"] for d in common])
        err = np.abs(ft - tt); pooled_err += list(err); pooled_bias += list(ft - tt)
        fev = ft <= FROST_TH; tev = tt <= FROST_TH
        tp, fp, fn, tn = int((fev & tev).sum()), int((fev & ~tev).sum()), int((~fev & tev).sum()), int((~fev & ~tev).sum())
        pooled["tp"] += tp; pooled["fp"] += fp; pooled["fn"] += fn; pooled["tn"] += tn
        # 基线：持续法（用前一日实况作为"预报"）
        persist = [abs(tt[i] - tt[i - 1]) for i in range(1, len(tt))]
        pooled_persist += persist
        per_year.append({"year": y, "n": len(common), "frost_days_truth": int(tev.sum()),
                         "tmin_mae": round(float(np.mean(err)), 2), "tmin_bias": round(float(np.mean(ft - tt)), 2),
                         "persist_tmin_mae": round(float(np.mean(persist)), 2) if persist else None,
                         "pod": round(tp / (tp + fn), 3) if (tp + fn) else None,
                         "far": round(fp / (tp + fp), 3) if (tp + fp) else None,
                         "csi": round(tp / (tp + fp + fn), 3) if (tp + fp + fn) else None})
    lo, hi = boot_ci(pooled_err)
    tp, fp, fn, tn = pooled["tp"], pooled["fp"], pooled["fn"], pooled["tn"]
    always_alarm_far = round((fp + tn) / max(1, tp + fp + fn + tn), 3)  # 全报警基线的空报率
    out["spring"] = {"years": years, "per_year": per_year,
                     "pooled": {"n": tp + fp + fn + tn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                                "tmin_mae": round(float(np.mean(pooled_err)), 2) if pooled_err else None,
                                "tmin_mae_ci95": [lo, hi],
                                "pod": round(tp / (tp + fn), 3) if (tp + fn) else None,
                                "far": round(fp / (tp + fp), 3) if (tp + fp) else None,
                                "csi": round(tp / (tp + fp + fn), 3) if (tp + fp + fn) else None,
                                "tmin_bias": round(float(np.mean(pooled_bias)), 2) if pooled_bias else None,
                                "baseline_always_alarm_far": always_alarm_far,
                                "baseline_persist_tmin_mae": round(float(np.mean(pooled_persist)), 2) if pooled_persist else None},
                     "note": "Historical Forecast 为归档预报（近实时口径，提前期≈0–1 天）；ERA5 为再分析真值，非茶园地面观测。"}

    os.makedirs(REPORT, exist_ok=True)
    json.dump(out, open(os.path.join(REPORT, "forecast_verify.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    md = ["# 提前期与多年春采季预报验证（权威在线数据）\n",
          f"> 站点：梅家坞（{LAT}N,{LON}E）｜生成：{out['generated']}",
          f"> 实况：ERA5（再分析，非茶园地面观测）｜预报：Open-Meteo Previous Runs / Historical Forecast\n",
          "## A. 提前期误差（Previous Runs vs ERA5，窗口 %s ~ %s）" % (start, end),
          "| 提前期 | 样本 | Tmin MAE | MAE 95%CI | Tmin bias | Tmax MAE | 降水 MAE | POD | FAR | CSI |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in leads:
        md.append(f"| {r['lead']}天 | {r['n']} | {r['tmin_mae']} | {r['tmin_mae_ci95']} | {r['tmin_bias']} | {r['tmax_mae']} | {r['precip_mae']} | {r['pod']} | {r['far']} | {r['csi']} |")
    md += ["", "## B. 多年春采季（2–4 月）霜冻（Historical Forecast vs ERA5）",
           "| 年份 | 样本 | 实况霜冻日 | Tmin MAE | 持续法 MAE | POD | FAR | CSI |",
           "|---|---|---|---|---|---|---|---|"]
    for r in per_year:
        md.append(f"| {r['year']} | {r['n']} | {r['frost_days_truth']} | {r['tmin_mae']} | {r['persist_tmin_mae']} | {r['pod']} | {r['far']} | {r['csi']} |")
    p = out["spring"]["pooled"]
    md += ["", "**汇总**：%s" % json.dumps(p, ensure_ascii=False),
           "", f"> 说明：{out['spring']['note']}",
           "> 全报警基线空报率 ≈ %s（越低越好）；持续法为朴素基线。" % p.get("baseline_always_alarm_far")]
    open(os.path.join(REPORT, "forecast_verify.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md))
    print("-> report/forecast_verify.{md,json}")


if __name__ == "__main__":
    main()