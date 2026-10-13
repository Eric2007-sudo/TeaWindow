# 自研问答意图分类器（本机 numpy）

- 类别 16；训练 2401，评测 146，挑战集 45；字符 1-2gram 特征 2714 维。
- **评测准确率 = 74.7%**；挑战集准确率 = 73.3%

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
- oos: 21 条
- pick_window: 8 条
- plot: 8 条
- rain: 8 条
- risk_today: 10 条
- schedule: 8 条
- value: 8 条

## 样例预测
- “会不会有晚霜” → frost（真值 frost）✓
- “什么时候采最好” → pick_window（真值 pick_window）✓
- “彩票怎么买” → oos（真值 oos）✓
- “要不要等两天再采” → decision（真值 decision）✓
- “每亩能省多少” → value（真值 value）✓
- “低温冻害严不严重” → frost（真值 frost）✓
- “是不是该灌溉了” → decision（真值 drought）✗
- “怎么申请信用卡” → oos（真值 oos）✓
- “这两天适不适合采摘” → pick_window（真值 pick_window）✓
- “有没有卫星数据” → data_source（真值 data_source）✓
- “明前采摘窗口” → pick_window（真值 pick_window）✓
- “孩子发烧了怎么办” → oos（真值 oos）✓