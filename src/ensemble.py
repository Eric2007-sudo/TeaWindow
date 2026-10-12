"""
集合预报不确定性：用 Open-Meteo 集合接口（多模式多成员），
逐日给出霜冻概率 P(Tmin≤2)、高温概率 P(Tmax≥35) 与温度分位区间。
输出 data/processed/ensemble.json
"""
import json
import os
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
LAT, LON = 30.2139, 120.0961
MODELS = "gfs_seamless,ecmwf_ifs025,icon_seamless"
UA = {"User-Agent": "TeaWindow/1.0"}


def main():
    os.makedirs(PROC, exist_ok=True)
    url = ("https://ensemble-api.open-meteo.com/v1/ensemble"
           f"?latitude={LAT}&longitude={LON}&hourly=temperature_2m"
           f"&models={MODELS}&forecast_days=16&timezone=Asia%2FShanghai")
    raw = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read())
    h = raw["hourly"]
    times = h["time"]
    members = [k for k in h if k.startswith("temperature_2m")]
    dates = np.array([t[:10] for t in times])
    uniq = sorted(set(dates.tolist()))

    per_day = {d: {"tmins": [], "tmaxs": []} for d in uniq}
    for mk in members:
        vals = np.array(h[mk], dtype=float)
        for d in uniq:
            m = dates == d
            v = vals[m]
            if len(v) and not np.all(np.isnan(v)):
                per_day[d]["tmins"].append(np.nanmin(v))
                per_day[d]["tmaxs"].append(np.nanmax(v))

    series = []
    for d in uniq:
        tmin = np.array(per_day[d]["tmins"], dtype=float)
        tmax = np.array(per_day[d]["tmaxs"], dtype=float)
        if len(tmin) == 0:
            continue
        series.append({
            "date": d,
            "n_members": int(len(tmin)),
            "p_frost": round(float((tmin <= 2).mean()), 3),
            "p_heat": round(float((tmax >= 35).mean()), 3),
            "tmin_p10": round(float(np.nanpercentile(tmin, 10)), 1),
            "tmin_p50": round(float(np.nanpercentile(tmin, 50)), 1),
            "tmin_p90": round(float(np.nanpercentile(tmin, 90)), 1),
            "tmax_p10": round(float(np.nanpercentile(tmax, 10)), 1),
            "tmax_p50": round(float(np.nanpercentile(tmax, 50)), 1),
            "tmax_p90": round(float(np.nanpercentile(tmax, 90)), 1),
        })

    out = {
        "models": MODELS,
        "n_members": len(members),
        "series": series,
        "method": "Open-Meteo ensemble（多模式多成员）逐日 Tmin/Tmax 分布；"
                  "p_frost=P(Tmin≤2℃)，p_heat=P(Tmax≥35℃)。",
        "caveat": "集合成员数有限，概率为集合频率估计；仅覆盖预报期。",
    }
    with open(os.path.join(PROC, "ensemble.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"成员数={len(members)}，天数={len(series)}")
    for s in series[:6]:
        print(f"  {s['date']}: p_frost={s['p_frost']} p_heat={s['p_heat']} "
              f"Tmin[{s['tmin_p10']},{s['tmin_p50']},{s['tmin_p90']}] "
              f"Tmax[{s['tmax_p10']},{s['tmax_p50']},{s['tmax_p90']}]")
    print("-> data/processed/ensemble.json")


if __name__ == "__main__":
    main()
