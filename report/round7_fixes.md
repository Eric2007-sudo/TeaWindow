# 第七轮：第三轮复测 + 专项深度评测 P0 整改

> 依据：`TeaWindow产品第三轮复测评估报告_2026-10-14.md`、`TeaWindow预测精准性_数据权威性_交互体验专项深度评测_2026-10-14.md`。
> 目标：把"局部正确、整体不一致"收敛为可验证的业务不变量。测试：`python -m pytest -q` → **61 passed**。

## 一、统一季节策略 + 北京时间（P0）
- 新增 `src/season.py`：`policy()` 返回共享对象 `{season, allowed_actions, forbidden_actions, reason}`；`today()/now()` 统一 **Asia/Shanghai**。
- 所有环节消费同一策略：`build_export` / `decision` / `scheduler` / `qa/nlg` / `qa/engine` / `serve`。
- **跨意图修复**：`frost`/`heat`/`risk_today` 在非春采期**不再输出"可正常采/适合采"**，改附养护提示；`decision` 非春采期直接返回养护（不再格式化空 `decision.days`）。
- 证据：`test_offseason_frost_no_pick`、`test_offseason_decision_no_none`；线上 `season=off`。

## 二、业务日与时段（P0）
- 服务端 `_cur_day` / `data_age_days` / 季节边界改用北京时间，修复"北京时间 00:00–07:59 把昨天当今天"。
- 前端 `app.js` / `chat.js` 日期与时间戳改用 `Asia/Shanghai`。
- **日期槽位**：`qa/nlg._parse_abs_date` 支持 `2026年10月20日 / 10月20日 / 2026-10-20`；历史日期走历史数据，超出范围**明确拒绝**；`48小时/24小时` 解析为**时段**（非"后天"）。
- 新增 `rain_max`（哪天雨最大→给具体日期）、`compare`（今天 vs 明天）。
- 证据：`test_absolute_date_answered`、`test_historical_out_of_range_refused`、`test_rain_max_gives_date`、`test_48h_is_horizon_not_day`。

## 三、输出完整性（P0）
- `season.clean_text()` 统一清理/兜底；`nlg.fallback`、`decision`、`risk_today` 等消除 `None`。
- 证据：`test_output_integrity_no_placeholders`（对多类问题断言不含 `None/NaN/undefined/建议-`）。

## 四、history 强类型 + 空白输入（P0）
- `HistoryMessage{role: Literal['user','assistant'], content: 1–1000}`；`history` 最多 20 条；非法元素/角色/空内容/超长 → **422**。
- `question` 先 `trim` 再校验：`""`/空格/Tab/换行 → **422**。
- 无有效历史的 `继续/然后` → **澄清**，不再进入决策模板。
- 证据：`test_blank_question_422`、`test_invalid_history_422`、`test_bare_continue_without_history_clarifies`。

## 五、口径与水量符号（P0）
- **风险口径**：来源链明确"展示 R 为**专家规则风险**，GBDT 概率为辅助"；`model` 意图直接回答 AUC 口径/漏报/局限（不再复述宣传模板）。
- **水量符号**：`water_deficit_10d = ET0 − 降水`，**负值为盈余**；`drought` 与 `day_advice` 修正描述；当"连旱但水量盈余"冲突时只建议**巡查/测墒**，不直接要求灌溉，并标注土壤水分为**模式估计**（非田间实测）。
- 证据：`test_drought_water_sign`、`test_risk_provenance_mentions_rule`。

## 六、上下文与交互（P1 部分）
- 复合问题**拆解**：命中多个主题意图时逐项回答。
- 否定/改口：`_strip_negations` 删除被否定关键词（"不要回答霜冻，我想问雨"→ rain_max）。
- 前端：`app.js` 增加**离线/缓存（非实时）横幅**；对后端字段做 HTML 转义（`esc`）以降低 `innerHTML` 注入面；`chat.js` 增加**欢迎语+当前数据状态+能力边界**、北京时间时间戳。
- OpenAPI：`HistoryMessage`/`SensorReq` 作为 typed items；`AskResp/SummaryResp/ErrorResp`。

## 七、仍未解决（需真实数据/资源）
- 弱标签循环论证、无负事件对照与完整春采季**前瞻性盲测**；物候未超固定日期基线；
- 逐日**预报快照档案**（1/3/7/14 天真实误差）尚未建立；
- 多实例/外部数据库/设备级凭证与审计、监控告警、CSP `style-src` 收紧、真机并发压测（502 根因）。