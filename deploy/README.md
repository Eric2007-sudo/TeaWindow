# 部署指南

TeaWindow 支持两种上线方式，二者可同时使用。

## Tier 1 · 静态仪表盘（保底，5 分钟）
静态站点即 `web/`（`index.html` + `app.js` + `data.js` + `chart.umd.min.js`），**离线可运行**。
- **Cloudflare Pages**：新建项目 → Direct Upload → 上传 `web/` 目录 → 得到公网链接。
- **GitHub Pages**：把 `web/` 推到仓库 → Settings → Pages → 选择目录。
- 说明：静态页读内嵌 `data.js`；若要每日更新，需重跑 `python src\pipeline.py` 后重新上传。

## Tier 2 · 实时服务（FastAPI，推荐）
`src/serve.py` 提供服务 + 每日定时刷新，静态页会自动优先读 `/api/overview`。

### 本地
```powershell
pip install -r requirements.txt
python src\serve.py            # http://127.0.0.1:8000
# 或
uvicorn src.serve:app --reload --port 8000
```

### Render
1. 新建 Web Service，连接本仓库。
2. Build：`pip install -r requirements.txt`
3. Start：`uvicorn src.serve:app --host 0.0.0.0 --port $PORT`
4. 环境变量：`DEEPSEEK_API_KEY`（可选）。
   可直接使用 `deploy/render.yaml`（Blueprint）。

### Railway / Heroku
使用 `deploy/Procfile`：`web: uvicorn src.serve:app --host 0.0.0.0 --port $PORT`。

### Docker
```bash
docker build -f deploy/Dockerfile -t teawindow .
docker run -p 8000:8000 -e DEEPSEEK_API_KEY=sk-xxx teawindow
```

## API
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务与数据状态 |
| GET | `/api/overview` | 前端完整数据（同 `data.json`） |
| GET | `/api/summary` | 今日/未来 7 天风险、采摘窗口、指标 |
| GET | `/api/days?scope=recent\|forecast\|history` | 逐日数据 |
| GET | `/api/advice?date=YYYY-MM-DD` | 单日建议（DeepSeek，带缓存） |
| POST | `/api/refresh` | 触发管线刷新（后台执行） |

> 定时任务：`serve.py` 内置 `apscheduler`，每日 **06:00（Asia/Shanghai）** 自动刷新数据。

## 注意事项
- `.env`（含密钥）**不要**提交或打进镜像（已 `.gitignore` / `.dockerignore`）。
- 首次部署若无 `web/data.json`，服务启动时会自动跑一次管线（需联网）。
- 国内访问海外平台可能较慢，演示优先用 **Tier 1 静态页**或本地服务。
