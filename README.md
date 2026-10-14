# 梅坞采候 · TeaWindow

> **梅家坞（西湖龙井核心产区）龙井 43 号「倒春寒 × 高温」复合风险预警与采摘窗口决策助手**
>
> AI4Climate 全球青年气候解决方案挑战赛 · 赛道 01「梅家坞气候智慧茶园」

TeaWindow 用一个**可运行、可验证**的离线原型，回答茶农每天最关心的三件事：
**今天有没有风险？风险是什么？现在该采还是该防？**

**在线访问**
- 静态仪表盘（离线可跑）：https://eric2007-sudo.github.io/TeaWindow/
- 实时服务（API + 每日自动刷新）：https://teawindow.onrender.com

## 1. 解决什么问题

梅家坞约 **70%** 茶园种植的是**特早生、抗旱弱**的**龙井 43 号**，因此同时暴露于两类气候风险：

- **春季倒春寒/霜冻**：萌芽早，嫩芽易被晚霜打伤（2010 年浙江冻害损失约 **17 亿元**）。
- **夏季高温/伏旱**：叶片灼伤、影响来年春茶（2020、2022 年西湖区约 **5000 亩**灼伤；2024 年杭州高温日 **60 天**破纪录）。
- 叠加**连阴雨/台风**等，构成**复合风险**，且气象+遥感+地形信号分散、难以判读。

## 2. 方案（气象指标 + 机器学习 + 遥感 + LLM）

```
Open-Meteo 气象(历史+预报)          NASA GIBS / Sentinel-2 遥感
        │                                   │
        ▼                                   ▼
  农业气象指标引擎                    植被活力(NDVI 近似)
 (积温/霜冻/倒春寒/高温/水分亏缺/连阴雨)      │
        └───────────────┬───────────────────┘
                        ▼
             numpy GBDT 复合风险识别  ──►  风险等级(低/中/高/极高)
                        │
                        ▼
             透明规则：采摘适宜度 + 最佳采摘窗口
                        │
                        ▼
        LLM(DeepSeek) / 规则后备：白话行动建议
                        │
                        ▼
              单页离线仪表盘 web/index.html
```

## 3. 目录结构

```
TeaWindow/
├─ README.md · PLAN.md · LICENSE(MIT) · LICENSE-DATA(CC BY 4.0) · CITATION.cff
├─ requirements.txt · .env.example · run_all.ps1
├─ src/
│  ├─ fetch_weather.py   # 抓取 Open-Meteo 历史(2015+)+16天预报
│  ├─ fetch_station.py   # Meteostat 杭州站真实观测（一手观测）+ 交叉验证
│  ├─ station_correct.py # 用台站观测对 ERA5 做逐月偏差订正
│  ├─ sensor_ingest.py   # 接入外部/自建传感器 CSV → 计算指标
│  ├─ indices.py         # 农业气象指标引擎
│  ├─ fetch_ndvi.py      # MODIS NDVI(真实,颜色反演) + Sentinel-2 场景清单
│  ├─ fetch_s2_ndvi.py   # 真实 Sentinel-2 数值 NDVI（COG 概览窗口读取；需网络可达 S3）
│  ├─ terrain.py         # 地块级地形（Open-Meteo DEM）→ 霜冻易感
│  ├─ model.py           # numpy GBDT 复合风险模型 + 逐年前推验证
│  ├─ calibrate.py       # 概率校准(Platt)+bootstrap 置信区间
│  ├─ ensemble.py        # 集合预报 → 霜冻/高温概率与温度分位
│  ├─ backtest_events.py # 真实事件回测（事件级）
│  ├─ phenology.py       # 物候外部真值：官方开采日 vs GDD 预测
│  ├─ model_compare.py   # 三模型对照 + 预警提前量
│  ├─ label_sensitivity.py # 弱标签鲁棒性 + 特征消融
│  ├─ index_insurance.py # 天气指数保险触发
│  ├─ scheduler.py       # 采摘调度优化（产能约束下）
│  ├─ decision.py        # 决策论建议（抢采/等待/防护 期望效用）
│  ├─ counterfactual.py  # 反事实归因（防护减损）
│  ├─ value.py           # 价值闭环（预期损失/保费/减损）
│  ├─ recalibrate.py     # 众包物候闭环（复校 GDD 阈值）
│  ├─ llm_advice.py      # DeepSeek 白话建议（带规则后备）
│  ├─ pipeline.py · serve.py · build_export.py · make_figs.py · make_qr.py · deploy_render.py
├─ tests/                # pytest 单元测试
├─ src/qa/               # 自研问答：build_corpus · train_intent_local · engine · nlg · build_d2t
├─ gpu/                  # GPU 训练脚本：train_intent_bert · train_embedder · predict_intent · train_d2t · export_onnx · infer_d2t
├─ data/qa/              # 问答语料/知识库/意图标注
├─ data/ raw · processed # 原始与处理后数据
├─ models/               # metrics.json · calibration.json
├─ report/ analysis.md   # AI 模型与分析报告 + figures/
├─ submit/               # 提交三件套 + 路演稿 + 商业模式 + 截图 + 英文版
├─ research/             # 调研：一手数据方案/证据台账/信息公开/合作/自建传感器
├─ deploy/               # Dockerfile · Procfile · render.yaml · 上线清单
├─ .github/workflows/    # pages.yml · refresh.yml · test.yml
└─ web/ index.html app.js data.js chart.umd.min.js demo.html links.html chat.html report.html (demo_assets/)
```

## 4. 快速开始

```powershell
# 依赖
pip install -r requirements.txt

# 方式一：一键（抓数→指标→遥感→模型→导出→起服务）
.\run_all.ps1                 # 联网全量
.\run_all.ps1 -NoFetch        # 用本地数据重算

# 方式二：分步
python src\fetch_weather.py
python src\fetch_ndvi.py
python src\indices.py
python src\terrain.py
python src\model.py
python src\calibrate.py
python src\ensemble.py
$env:DEEPSEEK_API_KEY="sk-..."   # 可选；不设则用规则模板
python src\build_export.py
start web\index.html             # 离线双击即可

# 方式三：在线服务
python src\serve.py              # http://127.0.0.1:8000
```

## 5. 离线 / 在线 Demo

`web/index.html` 为**自包含单页**：优先读取实时接口 `/api/overview`，失败则回退内嵌 `data.js`，
**双击即可离线运行**，适合演示视频录制。包含：风险/适宜度时间线、气温与霜冻/高温信号、
NDVI 植被活力、**地块级地形与霜冻易感**、未来 16 天预报表（含**霜冻/高温概率**）与白话建议、模型指标与数据来源。

**在线活服务**（FastAPI）：见 `deploy/README.md`。内置 `apscheduler` 每日 06:00 自动刷新；API 见该文档。

## 6. 数据来源（全部公开、免密钥）

| 用途 | 来源 |
|---|---|
| 气象（历史+预报） | Open-Meteo（ERA5 再分析 + 预报） |
| **真实台站观测（一手）** | Meteostat 杭州站 WMO 58457（逐日观测） |
| 植被活力 | NASA GIBS `MODIS_Terra_NDVI_8Day`（颜色近似反演） |
| 高分辨率能力证明 | Element84 Earth Search `sentinel-2-l2a`（STAC 场景清单） |
| 地块地形（DEM） | Open-Meteo Elevation（90m，海拔/坡度/坡向） |
| 预报不确定性 | Open-Meteo Ensemble（GFS/ECMWF/ICON，122 成员） |
| LLM 建议（可选） | DeepSeek `deepseek-chat` |

坐标：梅家坞 **30.2139°N, 120.0961°E**。

## 7. 免责声明

本原型为**决策辅助**，输出存在不确定性，**不替代**田间实勘、农技指导与官方气象预警。
涉及灾害预警时请以**杭州市气象局**等官方发布为准。详见 `report/analysis.md`。

## 8. 自播放演示 / 打包 / 许可

- **自播放演示页**（录屏用）：`web/demo.html`（自动巡览 + 字幕，空格暂停，←/→ 切换）
- **一键打包**：`dist/TeaWindow_v1.3.zip`；**GitHub Release**：https://github.com/Eric2007-sudo/TeaWindow/releases/tag/v1.3
- **测试与 CI**：`tests/`（pytest，**103 passed**）、`.github/workflows/test.yml`
- **发布一致性自检**：`src/deploy_check.py`、`.github/workflows/deploy_check.yml`、`/api/ready`、`/api/alerts`
- **持久化（已接入）**：Render Postgres + `DATABASE_URL`；`/api/persistence`；`src/persistence_check.py`（跨重部署保留验收 PASS）
- **外部定时器**：`.github/workflows/verify.yml`（每 6h 触发验证刷新）；`.github/workflows/refresh.yml`（每日刷新）
- **质量整改（对照四轮评测）**：`submit/13_评估整改说明.md`、`report/round7_fixes.md`、`report/round8_fixes.md`
  （统一季节策略 + 北京时间、日期槽位/目标日一致、history 强类型、输出完整性、灌溉先测墒、数据权威深答）
- **数据治理与接口**：`submit/16_数据治理与接口.md`（提前期真实误差 `/api/forecast/verify`、数据版本 `/api/data/versions`、设备凭证/审计、田间结果 `/api/outcome`、`/api/metrics`、`/api/updates`）
- **提前期误差报告**：`report/forecast_verify.md`（Open-Meteo Previous Runs vs ERA5，1/3/7 天）
- **外部定时刷新**：`.github/workflows/refresh.yml`（每日 06:00 CST 调用线上 `/api/refresh`）
- **许可证**：代码 **MIT**（`LICENSE`）· 数据与文档 **CC BY 4.0**（`LICENSE-DATA.md`）
- **引用**：见 `CITATION.cff`
