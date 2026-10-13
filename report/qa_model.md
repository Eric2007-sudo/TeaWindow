# 自研问答意图分类器（本机 numpy）

- 类别 15；训练 580，评测 35；字符 1-2gram 特征 1292 维。
- **评测准确率 = 80.0%**

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
- “遥感数据是什么” → data_source（真值 data_source）✓
- “夜里温度会不会太低冻伤嫩芽” → frost（真值 frost）✓
- “谢谢啦” → greet（真值 greet）✓
- “雨天鲜叶怎么处理” → rain（真值 rain）✓
- “最近会倒春寒吗” → frost（真值 frost）✓
- “你好，问个问题” → greet（真值 greet）✓
- “土壤太湿会不会沤根” → frost（真值 rain）✗
- “该抢采还是再等等” → decision（真值 decision）✓
- “现在茶树有没有危险” → risk_today（真值 risk_today）✓
- “几天没下雨了” → rain（真值 drought）✗
- “这几天会不会太热” → heat（真值 heat）✓
- “现在有没有什么风险” → risk_today（真值 risk_today）✓