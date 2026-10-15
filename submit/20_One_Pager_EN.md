# TeaWindow — One-Pager (EN)

**Challenge track:** Climate-smart tea farming in Meijiawu · **Stage:** Prototype / demo available

## Problem
Meijiawu (30.21°N, 120.10°E) is a core West Lake Longjing area. About **70%** of gardens grow **Longjing 43** — early-budding and drought-sensitive. Spring late frost/cold spells, summer heat and drought, and prolonged rain/typhoons strike the harvest window. Evidence: **2010** Zhejiang cold event ~**1.5M mu (~100,000 ha)**, ~**RMB 1.7bn** losses (~30% of West Lake gardens hit, ~10-day delay); **2020/2022** ~**5,000 mu** heat-damaged; **2024** Hangzhou **60 high-temperature days**.

## Solution
TeaWindow turns public **weather + NDVI + terrain** into **daily compound-risk assessments** and **plain-language tea-garden actions** for farmers, harvesting teams, cooperatives and enterprises.

- **Data (public, key-free):** Open-Meteo **ERA5 history** + **MET Norway forecast** (dual-source with fallback), NASA GIBS **MODIS NDVI**, **Sentinel-2** (catalog), **Copernicus DEM**.
- **Indicators:** GDD, frost, cold spells, heat, consecutive dry days, water deficit, prolonged rainfall.
- **Model:** numpy **GBDT** for compound risk **R**; **ensemble** for uncertainty; terrain/NDVI for plot-level context.
- **Rules:** transparent harvest suitability, best windows, scheduling.
- **LLM:** DeepSeek **optional rephrasing only**; numbers come from the model/data, with a rule fallback.

## Why AI is necessary
A single threshold (e.g. Tmin) cannot capture **frost × heat × drought × crop-stage** interactions. On held-out 2024–2025, the multivariable GBDT reproduced expert risk labels better than a single-temperature baseline (**AUC 0.998 / F1 0.85 vs 0.78 / 0.50**; **weak-label**, not field accuracy).

## Validation
- Spring frost 2022–2025 (Feb–Apr) vs ERA5 over **357 days**: Tmin **MAE 1.32°C (95% CI 1.21–1.43)** vs **2.08°C** persistence; lead-time MAE **0.49 / 0.67 / 0.91°C** at 1/3/7 days.
- Frost events: **POD 0.709, FAR 0, CSI 0.709** (73 TP / 30 missed).
- Multi-year event backtest: **7/7**.
- Next: freeze forecast versions; compare with **plot-level sensors** and **explicit positive/negative field reports**.

## Differentiation
Plot-level, compound, and actionable — not a replacement for official warnings. Decision support with provenance (upstream URL, params, full SHA-256, fetch time) and stale-data degradation.

## Impact
Shifts tea farming from "following the sky" to **acting 1–7 days ahead** (harvest scheduling, frost protection, irrigation, drainage, shade), plus **weather-index insurance** pricing support.

## Links
- Live demo: https://teawindow.onrender.com/
- Static dashboard: https://eric2007-sudo.github.io/TeaWindow/
- Open-source repo: https://github.com/Eric2007-sudo/TeaWindow

## Boundary
Prototype / research aid. **Decision support only** — to be checked against field conditions and official warnings.

> **One Place · One Climate Problem · One AI Solution**