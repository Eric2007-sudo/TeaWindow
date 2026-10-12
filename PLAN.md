# TeaWindow 执行计划（在线活服务 + 加分项）

> 目标：把离线 Demo 升级为**公网可访问的实时服务**，并补齐 3 项加分能力。
> 形态：Tier1 静态页（保底）+ Tier2 FastAPI 实时服务。

## 里程碑
| 天 | 交付 | 状态 |
|---|---|---|
| D1 | `pipeline.py` 一键化、`serve.py`（FastAPI）本地跑通、`web` 在线/离线双模式、`run_all.ps1` | ✅ 完成 |
| D2 | `terrain.py` 地块级地形、`calibrate.py` 概率校准+置信区间、移动端适配 | ✅ 完成 |
| D3 | `ensemble.py` 集合预报不确定性、更新截图与材料 | ✅ 完成 |
| D4 | `deploy/` 部署文件、英文版、打包、提交核对 | ✅ 完成 |

## 新增文件
```
PLAN.md · run_all.ps1
src/pipeline.py      # 一键：fetch → indices → ndvi → model → export
src/serve.py         # FastAPI：静态站点 + REST API + 每日定时刷新
src/terrain.py       # Open-Meteo elevation 多地块（海拔/坡向）
src/calibrate.py     # numpy Platt/isotonic 校准 + bootstrap 置信区间
src/ensemble.py      # Open-Meteo 集合预报 → 预报期不确定性
deploy/              # Dockerfile · Procfile · render.yaml
```

## API 草案（FastAPI）
- `GET /api/health`　服务状态
- `GET /api/overview`　等同于 `data.json`（供前端在线读取）
- `GET /api/summary`　今日风险 / 未来 7 天最高风险 / 推荐窗口 / 模型指标
- `GET /api/days?scope=recent|forecast`　图表与表格数据
- `GET /api/advice?date=YYYY-MM-DD`　DeepSeek 建议（带内存缓存）
- `POST /api/refresh`　触发管线刷新（`apscheduler` 每日 06:00 自动）

## 部署（两层）
- **Tier1（保底）**：静态 `web/` → Cloudflare Pages / GitHub Pages。
- **Tier2（实时）**：FastAPI → Render / Railway / HF Spaces 免费层。

## 验收
- 本地 `uvicorn src.serve:app --reload` 起服务，各接口 `curl` 正常；
- 前端在线模式读 API、离线模式读 `data.js`，两者均无报错；
- 指标与截图刷新；`run_all.ps1` 一键可复现。

## 已完成（第二轮）
- [x] **#8 台站偏差订正**：`src/station_correct.py` → `daily_corrected.csv`、`report/station_correction.md`
- [x] **A1 外部定时刷新**：`.github/workflows/refresh.yml`（每日 06:00 CST 调 `/api/refresh`）
- [x] **A2 单元测试+CI**：`tests/` + `.github/workflows/test.yml`（本地 5 passed）
- [x] **A3 许可+规范**：`LICENSE`(MIT)、`LICENSE-DATA.md`(CC BY 4.0)、`CITATION.cff`、仓库描述/话题
- [x] **B4 自播放演示**：`web/demo.html`（自动巡览+字幕）
- [x] **D9 商业模式**：`submit/06_商业模式.md`（含联网调研的定价锚点与来源）
- [x] **D10 Release**：`v1.3`（附 `TeaWindow_v1.3.zip`）
- [x] 在线服务：https://teawindow.onrender.com ｜ 静态：https://eric2007-sudo.github.io/TeaWindow/
