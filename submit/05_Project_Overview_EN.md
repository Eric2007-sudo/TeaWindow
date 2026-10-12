# TeaWindow — Project Overview (EN)

**Meijiawu (West Lake Longjing core area): a decision assistant for compound climate risk and tea-picking windows on Longjing-43.**

Track 01 · AI4Climate Global Youth Climate Solutions Challenge

## 1. The problem
About **70%** of Meijiawu tea gardens grow **Longjing-43**, an **early-budding, drought-sensitive** cultivar. It faces two hazards at once:
- **Spring cold spells / frost** on early buds — e.g. a 2010 freeze caused ~**¥1.7 bn** losses across Zhejiang.
- **Summer heat / drought** — ~**5000 mu** scorched in Xihu District in 2020/2022; Hangzhou hit a record **60 high-temp days** in 2024.
These compound with rainstorms/typhoons. Signals (weather, remote sensing, soil) are fragmented and hard for farmers to interpret.

## 2. Users
Meijiawu tea farmers, picking-team managers, cooperatives — and, by extension, the regional brand and consumers.

## 3. AI task (specific & necessary)
1. **Agro-meteorological engine**: growing-degree-days, frost, cold-spell, heat, drought (10-day water deficit + soil moisture), continuous rain.
2. **Compound-risk model (core AI)**: a **pure-numpy gradient-boosted trees (GBDT)** model fusing temperature/humidity/water-deficit/soil/phenology and their interactions.
3. **Picking suitability & window**: transparent rule → 0–100 score + best window.
4. **Remote sensing**: NASA GIBS MODIS NDVI (approximate) + Sentinel-2 STAC scene inventory.
5. **LLM advisory**: DeepSeek turns indices into actionable Chinese advice for farmers.

**Why AI**: a single threshold (e.g. Tmin≤2 °C for frost) only covers frost and over-alerts. On the **2024–2025 hold-out**,
the multivariate GBDT achieves **AUC 0.998 / F1 0.854**, vs a single-threshold baseline **AUC 0.780 / F1 0.498**.
AI adds value by capturing **compound interactions** and by propagating risk into the **forecast horizon**.

## 4. Solution pipeline
```
Open-Meteo weather (history+forecast)     NASA GIBS / Sentinel-2
        │                                         │
        ▼                                         ▼
  Agro-meteorological indices              Vegetation (NDVI)
        └───────────────┬─────────────────────────┘
                        ▼
        GBDT compound-risk model → low/medium/high/extreme
                        ▼
        Transparent rule: suitability + best picking window
                        ▼
        DeepSeek / rule fallback: actionable advisory
                        ▼
        Offline single-page dashboard (+ FastAPI live service)
```

## 5. Data & reproducibility
- Weather: **Open-Meteo** (ERA5 history 2015–2026, 4301 days + 16-day forecast). Public, key-free.
- Vegetation: **NASA GIBS** MODIS NDVI (color-inverted, approximate) + **Element84 STAC** Sentinel-2.
- Terrain: **Open-Meteo elevation** grid → slope/aspect → plot-level frost susceptibility.
- Uncertainty: **122-member ensemble** (GFS/ECMWF/ICON) → daily P(frost)/P(heat) and temperature quantiles.
- Model: pure-numpy GBDT (no scikit-learn/torch). Calibration (Platt) + bootstrap AUC CI.

## 6. Deliverables
- Offline single-page dashboard (`web/index.html`) — double-click to run.
- FastAPI live service (`src/serve.py`) with daily 06:00 refresh.
- Open-source code (`src/`), AI analysis report (`report/analysis.md`), and figures.

## 7. Ethics & safety
Framed as **decision support**, not a replacement for official warnings/agronomy advice. We disclose that the model uses
**weak (rule-derived) labels** and that remote sensing is **approximate**. Data are public/licensed; code and methods are transparent.

## 8. 90-day validation
Backtest against documented field events (D1–20) → 3–5 pilot gardens (D21–75) → calibration (D76–90).
Targets: event recall ≥80%, false-positive ≤20%, advisory adoption ≥60%, usability ≥4/5.
