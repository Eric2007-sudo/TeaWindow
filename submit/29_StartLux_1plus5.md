# StartLux-Decision 接入：1 + 5（生成 → 放行 → 事实核对）

> 日期：2026-10-23 ｜ 适用：TeaWindow `src/decision_client.py`、`src/qa/gate.py`、`tools/startlux_mcp.py`

## 0. 先纠正一个许可说法

仓库 README 写得很清楚：

- **代码**（推理引擎/HTTP server）：**Apache-2.0**；
- **模型权重**：**CC BY-NC 4.0**（非商用），商用需单独授权。

所以「Apache-2.0（商用需授权）」这个说法要改成：**代码 Apache-2.0，权重 CC BY-NC，商用需授权**。
参赛 Demo 属于非商用，可以用；但 PPT/文档里别写成"Apache-2.0 权重"。

## 1. 为什么是「1 + 5」

| 角色 | 谁来做 | 产出 |
|---|---|---|
| 生成（1） | **自研系统**：规则 + GBDT + 模板 | 数值、日期、行动建议（全部来自数据） |
| 放行（1） | **StartLux**：合规 / 可执行 / 不越界 | 概率 + 是否放行 |
| 事实核对（5） | **StartLux**：答案 vs 证据快照 | 支持度、可用度、是否需复核 |

关键点：**StartLux 不做生成，也不覆盖安全结论**。它是"第二个审稿人"，只在答案后面加提示或标记"需复核"。

## 2. 请求链路

```
用户问题
  → qa.engine.answer（规则/GBDT/模板）
  → _evidence_for_answer（当天数据行快照）
  → qa.gate.review（StartLux /v1/decisions）
      ├─ supported   : 数值/日期是否被证据支持
      ├─ actionable  : 是否给出今天能做的动作
      ├─ safe        : 是否避免绝对化承诺
      └─ usability   : 0 不可用 / 1 需复核 / 2 可直接用
  → decision: ok | review | annotate
  → 返回答案（review/annotate 时追加一行提示）
```

失败策略 **fail-open**：没配 key、超时、返回异常 → 原样返回自研答案，只在日志里记一笔。

## 3. TeaWindow 配置

`.env`（不要提交）：

```bash
STARTLUX_API_KEY=bk-...                       # 必填；Bamboo 控制台创建
STARTLUX_BASE_URL=https://api.bamboonode.dev/v1
STARTLUX_MODEL=startlux-decision-27b-autothink
STARTLUX_TIMEOUT=8                            # 单次调用超时（秒）
STARTLUX_GATE=1                               # 1=启用 1+5 护栏；0=关闭（默认）
STARTLUX_GATE_TIMEOUT=6                       # 护栏自己的超时
```

接口：

```bash
# 直接问决策模型（调试用）
curl -s $HOST/api/decide -H 'Content-Type: application/json' -d '{
  "state": {"risk":"低","tmin":12.4,"season":"off"},
  "questions": {"action":{"type":"choice","instructions":"今天该做什么？",
                           "criteria":{"采":"开采","防":"防冻","灌":"灌溉","观察":"常规管护"}}}
}'
```

```bash
# 走完整 1+5（护栏开启时，响应里会多一个 gate 字段）
curl -s $HOST/api/ask -H 'Content-Type: application/json' -d '{"question":"今天有风险吗","engine":"own"}'
```

响应示例：

```json
{"text":"2026-10-21：风险 低（R=0.0，适宜度 60）…",
 "gate":{"decision":"ok","scores":{"supported":0.93,"actionable":0.88,"safe":0.95,"usability":1.9}}}
```

`decision` 为 `review` / `annotate` 时，答案末尾会自动追加一行提示；`gate.decision=annotate` 表示证据一致性偏低，建议先核验。

## 4. 接入 opencode

**不要把它配成 chat provider**：opencode 的 provider 需要 OpenAI `chat/completions`，而 StartLux 是 `/v1/decisions`（类型化决策），协议不同。

正确做法：**本地 MCP 工具服务器**。

`opencode.jsonc`：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "startlux": {
        "type": "local",
        "command": ["python", "tools/startlux_mcp.py"],
        "environment": { "STARTLUX_API_KEY": "{env:STARTLUX_API_KEY}" }
      }
    }
  }
}
```

启动后 agent 会多出两个工具：

- `startlux_decide`：传 `state` + `questions`（choice/noul/score），返回每个选项的概率；
- `startlux_choose`：传 `state` + `instructions` + `options[]`，返回选中项与概率。

验证：

```bash
opencode mcp list          # 应显示 startlux connected
```

在会话里可以直接说："用 startlux_choose 判断这份补丁是否应该合并"，agent 会调用工具。

## 5. 什么时候值得用、什么时候别用

**值得**：意图路由（问题属于哪个意图）、是/否核查（这条答案是否被证据支持）、分级（风险/紧急度）、Agent 步骤放行。

**不值得**：写文案、生成报告、长链推理、需要外部知识的开放问答——它不是聊天模型。

**成本**：27B AutoThink 在不确定时会多想一步，护栏超时设 6 s；超时即 fail-open，不影响主流程。

## 6. 测试

```bash
python -m pytest tests/test_decision_client.py tests/test_gate.py -q
# 8 passed
python -m pytest -q
# 142 passed
```

未配置 key 时：`/api/decide` 返回 503；`/api/ask` 完全不受影响（护栏直接跳过）。

## 7. 答辩一句话

> 我们不把"决策"交给大模型：**自研系统负责生成可追溯的结论，StartLux 负责放行与事实核对**——它只能说"这条答案证据不足"，不能改数、不能替你拍板。

---

## 8. 闭环升级：数据体检 → 放行 → 有界修复

从 2026-10-23 起，/api/ask 的护栏从单次判定升级为三层闭环：

`
① 数据体检（确定性，不调模型）
   新鲜度 / 日期空洞 / 上游漂移 / 刷新状态 / 血缘  →  score 0–1
   两项以上关键项失败 → unreliable（强制 annotate）

② 放行 + 事实核对（StartLux）
   supported / actionable / safe / usability

③ 有界修复（最多 2 轮，仅对 annotate）
   加证据不足提示 → 再校验 → 通过即停
   review 只提示，不再多花一轮
`

关键约束：

- **修复动作是确定性的**（三条固定文案），不让模型重写结论；
- **最多 2 轮**，任何一轮失败立即停（fail-open）；
- 每轮 decision/scores 都进 gate.trace，可在 /qa_review.html 复核；
- 数据体检分数与失败项进 gate.data，评委能直接看到这条答案的依据可靠到什么程度。

## 9. 关于资源越多越准的边界

判断更准成立的前提是**有标签**。没有标签时，更多的算力只会让自我一致性更强，而不是更接近真值。所以我们不把闭环做成模型自评自改，而是：

1. 线上只做**有界修复**（不改数、不改行动）；
2. 离线用日志做**失败聚类**（按 intent / 失败项 / 数据体检项），人工确认后改规则或模板；
3. 每次改动都在**冻结评估集**（2024-01-01 → 2026-10-10）上回归，指标变差就回滚；
4. 真实精度仍要靠 90 天 pilot 的正/负样本，而不是模型置信度。

一句话：**闭环提升的是交付质量，不是自我进化**。

## 10. 离线反馈（只读日志）

```bash
python src/qa/feedback.py --limit 2000
# -> report/qa_feedback.md
```

产出：按 `intent × 失败项（证据/行动/边界/数据体检）` 的聚类、代表性问题，以及**外部真值基线**
（冻结评估集 AUC/F1、官方开采日 MAE）。它不改代码、不改权重，只告诉你"下一轮该看哪一类失败"。

日志现在同时保存：`chain`（来源链）、`evidence`（数据快照）、`gate`（每轮判定与数据体检），
管理员页 `/qa_review.html` 可直接看到"核对：ok · 证据 93% · 行动 67%"。

## 11. 预测辅助（不改数值）

`GET /api/forecast/assist?date=YYYY-MM-DD`

给定某一天，让 StartLux 只回答三件事：

| 问题 | 类型 | 用途 |
|---|---|---|
| 霜型（辐射霜 / 平流霜 / 无霜冻） | choice | 决定防霜措施优先级（谷底 vs 风口） |
| 预报置信（低/中/高） | score | 是否加"建议复核"提示 |
| 规则风险与气象条件是否一致 | noul | 发现规则与证据的分歧 |

**它不改 tmin/tmax/precip，也不改风险 R**；返回的是预测的元信息。结果按"日期 + 数据版本"缓存（首次 1.6 s，二次 0 s）。

要用它真正提升精度，必须先做一步实验：把"霜型/一致性"当**分组变量**，在冻结评估集上看各组的 Tmin 误差是否下降；没有下降就不进入模型。这条不做完，不能把"决策模型"写成"提高预测精度"。

```bash
curl -s "$HOST/api/forecast/assist?date=2026-10-27"
```
