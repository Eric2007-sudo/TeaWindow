# 第十一轮：第六轮评测 + 线上实测缺陷整改

> 依据：`TeaWindow产品第六轮全面复测报告_2026-10-14.md` 与线上实测（"将来一周…"未给逐日清单、置信度前后不一致）。测试：**96 passed**。

## 一、线上实测缺陷（用户反馈）
- **"将来一周有什么风险 / 我问将来一周每天情况"** 原返回单日 `risk_today`。→ 扩充触发词（将来/一周/这周/本周/每天/每日）→ 现返回**未来 7 天逐日清单** `forecast_list`。
- **置信度前后不一致**（0.8 / 0.68）。→ 命中强关键词固定 **0.9**、关键词固定 **0.85**，同一话题稳定；分类器路径才随文本浮动。
- 证据：`test_week_list_intents_and_stable_conf`。

## 二、P0 整改
1. **state 合并（覆盖式缺陷）**：`_extract_state(q, history, r, base)` 以传入 state 为**基底合并**；"那一天→它的最低温"多轮不再丢失 `active_date`；`/api/ask` 响应回传合并后 state。
   - 证据：`test_state_merge_three_turns`、`test_next_day_relative`（下一天/翌日/前日/大前天）。
2. **盲测负样本口径**：只有 **`巡查无灾`** 显式记录才算负样本；未上报日期记为 **unknown 不计入**；返回 `n_negatives/unknown_days/note`。
   - 证据：`test_outcome_negative_kind_and_ready_fields`。
3. **新鲜度阈值**：默认 150 → **60 分钟**（"100 分钟仍 fresh"不再发生）；`/api/ready` 纳入 **lineage_ok / refresh_ok / warnings**，血缘缺失或刷新未知不再静默 `ready=true`。
4. **数据血缘落地**：提交 `data/processed/fetch_meta.json`（上游 URL/参数/**原始响应 SHA-256**/抓取时间），启动快照即可填充 `upstream_url/params/raw_sha256_full`；启动即写 `refresh_state=startup`（不再 unknown）。

## 三、P1 整改
- **问答接入运行状态**：新增 `ops` 处理器 —— "多久刷新/是否过期"、"断网如何降级"、"提前期误差与运行批次" 直接作答（读 `refresh_state`/`data_versions`/`forecast_verify.json`）。
- **JSON 遵循用户字段**：`用JSON返回，字段为 date,tmin,rain,risk,action` → 精确输出该 5 字段（修复 `_normalize` 篡改字段名的问题：从**原问题**解析字段）。
- **Markdown 表格**：`format=table` 输出真实 Markdown 表格（日期/Tmax/Tmin/降水/风险）。
- **英文半支持**：大量英文 + 少量中文 → **明确拒绝**（避免"半翻译"误答），纯中文混合术语（明夭 frost risk）仍正常。
- 证据：`test_ops_questions`、`test_json_obeys_requested_fields`、`test_markdown_table_format`、`test_english_halflanguage_rejected`。

## 四、前端
- 主页预报表**只展示今天及未来**（与 `scope=forecast` 一致，标题与行数一致）。
- 聊天欢迎态增加**数据年龄（可能过期标记）**与**现场传感器状态**。

## 五、仍未完成（真实数据/资源）
- 题目要求的"运行闭环"仍需线上运行证据：持久卷/托管库挂载、`refresh.last_success` 非空、验证历史 ≥2 次、outcome 真实录入；
- 现场传感器真值；设备签名+nonce；提前期验证更早年份与田间真值；物候超越固定日期基线。