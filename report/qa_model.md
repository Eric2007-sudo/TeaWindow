# 自研问答意图分类器（本机 numpy）

- 类别 15；训练 2051，评测 125，挑战集 45；字符 1-2gram 特征 2142 维。
- **评测准确率 = 76.8%**；挑战集准确率 = 82.2%

## 各类分布（评测集）
- data_source: 8 条
- decision: 8 条
- drought: 9 条
- frost: 10 条
- greet: 7 条
- harvest_date: 8 条
- heat: 9 条
- insurance: 8 条
- model: 8 条
- pick_window: 8 条
- plot: 8 条
- rain: 8 条
- risk_today: 10 条
- schedule: 8 条
- value: 8 条

## 样例预测
- “谢谢你了” → greet（真值 greet）✓
- “为什么用机器学习” → harvest_date（真值 model）✗
- “今天需要注意什么风险” → risk_today（真值 risk_today）✓
- “防灾划算吗” → value（真值 value）✓
- “开采期大概几号” → harvest_date（真值 harvest_date）✓
- “北坡的茶园要注意啥” → plot（真值 plot）✓
- “你们的数据从哪来的” → data_source（真值 data_source）✓
- “用这个能减多少损” → value（真值 value）✓
- “会不会持续高温” → heat（真值 heat）✓
- “今天要不要注意点啥” → risk_today（真值 risk_today）✓
- “雨水多要不要开沟” → rain（真值 rain）✓
- “嫩芽会不会被冻” → frost（真值 frost）✓