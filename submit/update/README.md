# AI4Climate 最终轮 · 提交包

- 项目：**TeaWindow（梅坞采候）**
- 申请号：`AI4C-2026-MV94BFUH-4F403`
- 赛道：Track 01 · 梅家坞气候智慧茶园
- Demo：https://teawindow.onrender.com/
- 证据页：https://teawindow.onrender.com/evidence.html
- 仓库：https://github.com/Eric2007-sudo/TeaWindow

## 文件清单

| # | 文件 | 大小 | 说明 |
|---|---|---:|---|
| 01 | `01_TeaWindow_Pitch_EN.pptx` | 1.13 MB | 英文 PPT（12 页，评委主用） |
| 02 | `02_TeaWindow_Pitch_CN.pptx` | 1.08 MB | 中文 PPT（12 页，同版式） |
| 03 | `03_TeaWindow_Demo_EN.mp4` | 1.72 MB | 英文演示视频（2:48） |
| 04 | `04_TeaWindow_Demo_CN.mp4` | 1.78 MB | 中文演示视频（2:48） |
| 05 | `05_TeaWindow_Architecture_EN.pptx` | 0.35 MB | 英文 1+5 架构页（1 页） |
| 06 | `06_TeaWindow_Architecture_CN.pptx` | 0.42 MB | 中文 1+5 架构页（1 页） |
| 05 | `05_TeaWindow_Architecture_EN.png` | 0.34 MB | 英文架构页 PNG |
| 06 | `06_TeaWindow_Architecture_CN.png` | 0.41 MB | 中文架构页 PNG |


## 本轮新增（vs 10-17 提交版）

1. **1+5 可问责链**：自研生成 → 数据体检 → StartLux 放行/事实核对 → 有界修复（≤2 轮，fail-open）
2. **数据体检**：新鲜度 / 日期空洞 / 上游漂移 / 刷新状态 / 血缘 → score；两项关键失败强制提示
3. **预测辅助**：/api/forecast/assist（霜型 / 置信 / 一致性，不改数值，缓存 0.4 s）
4. **霜型实验**：1,033 个霜冻日验证，分组订正 MAE 1.00→1.03，**主动不上线**，只做元信息
5. **工程**：155 tests；冻结评估集指标不变（AUC 0.998 / F1 0.85）

## 提交建议

- **外籍嘉宾场**：01（英文 PPT）+ 03（英文视频）+ 05（英文架构页）
- **中文场**：02 + 04 + 06
- 若只能交一套：**优先英文版**
- 架构页可单独交，也可插到对应 PPT 的最后一页

## 规格核对

- PPT 均 12 页，< 30 MB
- 视频均 2:48（168 s），< 200 MB
- 架构页各 1 页

## 不要提交

- `key.md` / `.env` / 任何 API 密钥
- `report/judge_sim*.md`（内部自查，不宜给评委）
- 原始数据与中间产物（`data/processed/*`）

## 正文模板（邮件/表单）

> 项目：TeaWindow（梅坞采候），申请号 AI4C-2026-MV94BFUH-4F403。
> 附件：英文 PPT、英文视频、英文架构页（中文版见 02/04/06）。
> Demo：https://teawindow.onrender.com/ ｜ 证据页：/evidence.html ｜ 仓库：GitHub。
> 说明：本轮补充了 1+5 可问责链（自研生成 → 数据体检 → StartLux 放行/事实核对 → 有界修复），并公开了冻结评估集与官方开采日验证。
