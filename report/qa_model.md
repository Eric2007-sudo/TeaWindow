# 自研问答意图分类器（本机 numpy）

- 类别 15；训练 1561，评测 74；字符 1-2gram 特征 1934 维。
- **评测准确率 = 75.7%**

## 各类分布（评测集）
- data_source: 4 条
- decision: 5 条
- drought: 6 条
- frost: 6 条
- greet: 4 条
- harvest_date: 4 条
- heat: 6 条
- insurance: 4 条
- model: 5 条
- pick_window: 5 条
- plot: 4 条
- rain: 5 条
- risk_today: 6 条
- schedule: 5 条
- value: 5 条

## 样例预测
- “今年的采摘期怎么样” → harvest_date（真值 pick_window）✗
- “怎么安排采茶队” → schedule（真值 schedule）✓
- “茶树缺水了吗” → drought（真值 drought）✓
- “按什么顺序采摘” → pick_window（真值 schedule）✗
- “怎么保证不误报” → insurance（真值 model）✗
- “哪块地最危险” → plot（真值 plot）✓
- “明前茶什么时候开采” → harvest_date（真值 harvest_date）✓
- “茶叶保险怎么买” → insurance（真值 insurance）✓
- “低温冻害严不严重” → frost（真值 frost）✓
- “这两天能采茶吗” → pick_window（真值 pick_window）✓
- “连续晴热要不要灌水” → drought（真值 drought）✓
- “受灾怎么赔” → insurance（真值 insurance）✓