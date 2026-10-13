# 自研问答意图分类器（本机 numpy）

- 类别 15；训练 1015，评测 35；字符 1-2gram 特征 1532 维。
- **评测准确率 = 77.1%**

## 各类分布（评测集）
- data_source: 2 条
- decision: 4 条
- drought: 3 条
- frost: 3 条
- greet: 2 条
- harvest_date: 4 条
- heat: 2 条
- insurance: 2 条
- model: 1 条
- pick_window: 1 条
- plot: 3 条
- rain: 2 条
- risk_today: 4 条
- schedule: 0 条
- value: 2 条

## 样例预测
- “这几天会不会太热” → frost（真值 heat）✗
- “今年茶什么时候能采” → harvest_date（真值 harvest_date）✓
- “土壤太湿会不会沤根” → frost（真值 rain）✗
- “夜里温度会不会太低冻伤嫩芽” → frost（真值 frost）✓
- “怎么理赔” → insurance（真值 insurance）✓
- “最近会倒春寒吗” → frost（真值 frost）✓
- “要不要抢在霜冻前采” → decision（真值 decision）✓
- “雨天鲜叶怎么处理” → rain（真值 rain）✓
- “什么时候要防霜冻” → harvest_date（真值 frost）✗
- “开采时间比去年早还是晚” → harvest_date（真值 harvest_date）✓
- “用的什么数据” → data_source（真值 data_source）✓
- “今天适合上山干活吗” → risk_today（真值 risk_today）✓