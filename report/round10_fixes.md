# 第十轮：第五轮评测（实时性与适应性）P0/P1 整改

> 依据：`TeaWindow产品第五轮实时性与适应性全面复测报告_2026-10-14.md`。
> 主题：**把"速度"与"新鲜度"分开**，并把季节约束下沉到数据生成层。测试：`python -m pytest -q` → **81 passed**。

## 一、数据新鲜度闸门（P0）
- 新增 `_freshness()`：`fetched_at / age_minutes / stale / stale_threshold_minutes / refresh 状态 / build`。
- `/api/health`、`/api/summary` 均返回新鲜度；`/api/metrics` 返回 `data_age_minutes/data_stale/refresh/build`。
- 前端：`age_minutes > 150` 显示红色 **"数据约 X 分钟前获取（可能已过期）"** 横幅；离线另有横幅。
- 快照时间语义修正：`fetched_at` 记录**真实抓取时间**；启动时落版本标注"沿用已有数据（非新抓取）"，不再造成"刚刷新"错觉。
- `meta.updated/fetched_at` 统一为**北京时间**（不再 UTC 混用）。

## 二、刷新频率与状态（P0）
- 定时刷新：每日 06:00 **+ 每 3 小时**（`0/3/9/12/15/18/21 时 20 分`）。
- `store.refresh_state`：记录 `status/duration_s/error/last_success/next_planned`；`/api/metrics`、`/api/health` 可见；失败也会记录错误。
- `/api/refresh`（管理员/外部定时）走同一状态链路。

## 三、季节约束下沉到数据生成层（P0）
- 修复 `day_advice`：非春采期**任何一天**都不再输出"按一芽一叶标准采"（此前只在聊天出口打补丁）。
- 重新生成 `web/data.json`：`season:"off"` 时预报日建议**0 条**含"标准采"。第三方直读 `/api/days` 也不会拿到季节错误建议。
- 证据：`test_forecast_advice_no_pick_in_offseason`。

## 四、实时传感器语义（P0）
- `/api/realtime` 重写：`server_time`、`count/n`、`latest_observation_at`、`status(ok|no_sensors)`、`message`；每站 `observed_at/received_at/age_seconds/status(ok|stale|offline)`。
- 0 条时返回 **"尚未接入现场传感器（0 个站点上报）"**，不再用会变化的 `updated` 制造"实时"错觉。
- `updated` 保留为 `server_time` 别名（兼容前端）；`/api` 响应统一 `Cache-Control: no-store`。

## 五、真正的盲测评估（P0）
- `store.pilot_evaluate()`：把**冻结预测快照**按日期与**田间结果**配对，输出事件级 **TP/FP/FN/TN、precision、recall、false_alarm_rate、CSI、平均提前量**与样本明细；数据不足时返回 `pending` + 原因（`no_outcomes/no_hazard_outcomes/no_snapshots`）。
- `GET /api/pilot/evaluate`（管理员）直接返回该结果。

## 六、会话槽位与适应（P1）
- `/api/ask` 新增 `state`（结构化槽位），响应回传 `state`；前端携带并更新。
- 支持：`active_date` 实体继承、"**前一天/后一天/次日/昨天**"相对位移、"那一天/它"指代。
- **表达适应**：繁简/常见错字/中英术语归一（`未來→未来`、`採摘→采摘`、`frost→霜冻`…）；**中文数字日期**（"十月二十号"）。
- **输出格式**：请求 JSON → 返回结构化对象（`nlg.structured_answer`，数值与基础 API 一致）；表格请求走逐日字段列表。
- 证据：`test_chinese_numeral_date`、`test_json_format_output`、`test_state_prev_day_carry`。

## 七、监控与实时（P1/P2）
- `/api/metrics` 增 `latency_p50/p95/p99`、`data_age_minutes/data_stale/refresh/build`。
- `/api/updates?since=ISO`：**真增量**（只返回该时刻后新增观测）。
- 前端轮询统一为 15s，且**页面隐藏时暂停**。

## 八、部署一致性（P0）
- `/api/health`、`/api/data/versions` 暴露 **build（Git SHA）** 与版本；主页底部显示"数据版本 + 快照hash + 构建"。
- 说明：仍建议发布流程加入"路由数/核心接口"自动校验（下一轮）。

## 仍未完成（需真实数据/资源）
- 现场传感器实数据（`observed_at` 等语义已就绪，等设备接入）；
- 原始上游响应全量保存与运行批次（Open-Meteo Previous Runs 已可用于提前期误差）；
- 提前期验证跨 3–5 年并覆盖春采季霜冻事件；物候超越固定日期基线；
- 多实例/外部数据库、设备签名+nonce、告警通知通道（`/api/alerts`）。

## 九、发布一致性自检 + 告警（本轮补齐第五轮 P0）
- `GET /api/ready`（ready/build SHA/route_count/missing_critical/age/stale/refresh）与 `GET /api/alerts`（规则化告警）。
- `src/deploy_check.py`：部署后校验 health/ready(含 build SHA)/OpenAPI 路由数 ≥20/10 个核心接口/alerts，输出 PASS/FAIL 与退出码；`.github/workflows/deploy_check.yml` 每 3 小时自检。
- 数据血缘增强：`data/processed/fetch_meta.json`（上游 URL/参数/**原始响应 SHA-256**/抓取时间）；版本表增 `upstream_url/params/raw_sha256_full`。
- 测试 81 → **83**。

## 十、多年春采季验证 + GPU 训练（本轮）
### 10.1 多年春采季霜冻验证（权威在线）
- `src/forecast_verify.py` 扩展：**B) 多年春采季（2–4 月）**，Historical Forecast 归档 vs ERA5，给出逐年与汇总指标、bootstrap 95% CI、持续法与全报警基线。
- 结果（2022–2025，357 天）：**POD 0.709 / FAR 0.0 / CSI 0.709**，Tmin MAE **1.32**（CI [1.21,1.43]），优于持续法 MAE 2.08 与全报警基线（CSI≈0.29）。
- 诚实局限：归档预报提前期≈0–1 天；ERA5 非田间真值；Tmin 偏暖 +1.25℃ 导致约 29% 霜冻日漏报。

### 10.2 GPU 训练（易混样本增广）— 负结果
- 语料新增 **易混/硬样本（CONFUSE，约 90 条）** + 繁简/中英/口语变体，训练量 2401 → **2716**。
- 重训教师 `chinese-roberta-wwm-ext`：eval 93.8% / 挑战 95.6%（与上版持平）。
- 蒸馏学生 `rbt3`：eval **91.1%** / 挑战 86.7%，**低于**在线部署版（94.5% / 93.3%）。
- 嵌入（BGE）重训：检索 0.767 ≈ 现版 0.774，无提升。
- 决策：**保留在线部署模型**（`qa_intent_rbt3_oos` + `qa_embedder_onnx`）；本轮训练记为负结果，语料与脚本保留可复现。

## 十一、验证归档 + 告警通知（本轮）
- **验证入库血缘**：`verifications` 表（run 时间/build/SHA-256/汇总）；`/api/forecast/verify` 优先返回最新入库结果；`/api/forecast/verify/history` 历史；**每 6 小时**自动跑。
- **告警通知**：`ALERT_WEBHOOK_URL`；仅在告警**新增/变化**时推送（状态存 `alerts_state`）；**每 30 分钟**检查；`POST /api/alerts/test`（管理员）发测试；`/api/alerts` 增 `webhook_configured/notified`。
- 测试 83 → **85**。