---
marp: true
theme: default
paginate: true
title: TeaWindow Roadshow (EN)
---

# TeaWindow
## Compound climate-risk & picking-window assistant for Longjing-43 tea in Meijiawu (West Lake Longjing core area)

AI4Climate Global Youth Climate Solutions Challenge · Track 01

---

## 1. One line
**Turn scattered weather and satellite signals into one actionable sentence for farmers:
pick / shade / irrigate / protect-from-frost — today.**

---

## 2. The problem (real, specific)
- ~**70%** of Meijiawu gardens grow **Longjing-43** — early-budding and drought-sensitive.
- **Spring frost**: a 2010 freeze caused ~**¥1.7 bn** losses in Zhejiang.
- **Summer heat/drought**: ~**5000 mu** scorched in Xihu District (2020/2022).
- **2024**: Hangzhou hit a record **60 high-temp days** (41.9 °C on Aug 3).
- Compound hazards; fragmented signals; hard to interpret.

---

## 3. Users & pain points
- Users: Meijiawu **tea farmers, picking-team managers, cooperatives**.
- Three daily questions:
  1. Any risk today?
  2. What risk?
  3. Pick now, or protect now?

---

## 4. Solution pipeline
```
Open-Meteo weather (history+forecast)     NASA GIBS / Sentinel-2
        │                                         │
        ▼                                         ▼
  Agro-meteorological indices              Vegetation (NDVI)
        └───────────────┬─────────────────────────┘
                        ▼
        GBDT compound-risk model  →  low/medium/high/extreme
                        ▼
        Transparent rule: suitability + best picking window
                        ▼
        DeepSeek / rule fallback: actionable advisory
                        ▼
        Offline single-page dashboard + FastAPI live service
```

---

## 5. Why AI is necessary
- A single threshold (Tmin ≤ 2 °C) only covers frost and over-alerts.
- Our **gradient-boosted trees** fuse temperature, humidity, water deficit, soil, phenology and interactions.
- On the **2024–2025 hold-out**:

| Metric | TeaWindow GBDT | Single-threshold baseline |
|---|---|---|
| AUC | **0.998** | 0.780 |
| F1 | **0.854** | 0.498 |

---

## 6. Live demo
1. KPI cards: today's risk / next-7-day max / picking window / model metrics.
2. Risk & suitability timeline (forecast shaded).
3. Temperature with frost / heat / cold-spell markers.
4. 16-day forecast with **DeepSeek** advisories + frost/heat probabilities.
- Fully **offline-capable**; also a **live FastAPI service**.

Live: https://teawindow.onrender.com · Static: https://eric2007-sudo.github.io/TeaWindow/

---

## 7. Data & methods (open, key-free)
- Weather: Open-Meteo ERA5 2015–2026 (4301 days) + 16-day forecast.
- **Station observations**: Meteostat Hangzhou (WMO 58457, 4303 days) → cross-validation (r=0.98–0.99) + bias-correction.
- Remote sensing: NASA GIBS MODIS NDVI; **Sentinel-2 numeric NDVI** module (COG window read).
- Terrain: Open-Meteo elevation → slope/aspect → plot frost susceptibility.
- Uncertainty: 122-member ensemble → P(frost)/P(heat) + quantiles.
- LLM: DeepSeek.

---

## 8. Differentiation
| Axis | Official weather service | TeaWindow |
|---|---|---|
| Granularity | regional | **plot-level** |
| Risk | mainly frost | **frost × heat × drought × rain (compound)** |
| Output | elements/SMS | **actionable window + advisory** |
| User | departments | **farmers directly** |
| Loop | warn→SMS | **warn→act→feedback→verify** |

---

## 9. Validation & sustainability
- **90-day plan**: backtest (D1–20) → pilot 3–5 gardens (D21–75) → calibration (D76–90).
- Targets: event recall ≥80%, false-positive ≤20%, adoption ≥60%, usability ≥4/5.
- Payers: cooperatives, tea enterprises, insurers, government programs.
- Near-zero marginal cost (public data; pure-numpy model).

---

## 10. Ethics & openness
- Decision support, **not** a replacement for official warnings/agronomy advice.
- Honest disclosure: **weak (rule-derived) labels**; remote sensing is approximate.
- Open source (MIT; data/docs CC BY 4.0); reproducible; transferable to other regions.

---

## 11. Closing
**ONE PLACE · ONE CLIMATE PROBLEM · ONE AI SOLUTION**

TeaWindow — bringing AI into real tea gardens.

<!-- Q&A: official-service collaboration; label acquisition; scaling to other regions. -->
