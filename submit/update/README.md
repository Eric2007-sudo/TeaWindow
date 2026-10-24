# AI4Climate 最终轮 · 提交包

- 项目：**TeaWindow（梅坞采候）**
- 申请号：`AI4C-2026-MV94BFUH-4F403`
- 赛道：Track 01 · Climate-smart tea farming in Meijiawu
- Team lead：叶子玄（19）
- Region：China, Hangzhou ｜ Organisation：Zhejiang University
- Team size：1 ｜ Phone：+86 15858238044
- Stage：Prototype or demo exists
- Demo：https://teawindow.onrender.com/
- 证据页：https://teawindow.onrender.com/evidence.html
- 仓库：https://github.com/Eric2007-sudo/TeaWindow

## 文件（2 套 PPT + 1 段视频）

| # | 文件 | 大小 | 说明 |
|---|---|---:|---|
| 01 | `01_TeaWindow_Pitch_EN.pptx` | 1.40 MB | 英文 PPT（14 页：12 + 团队页 + 架构页） |
| 01 | `01_TeaWindow_Pitch_EN.pdf` | 0.85 MB | 英文 PDF（微信可直接预览） |
| 02 | `02_TeaWindow_Pitch_CN.pptx` | 1.47 MB | 中文 PPT（14 页：12 + 团队页 + 架构页） |
| 02 | `02_TeaWindow_Pitch_CN.pdf` | 1.10 MB | 中文 PDF（微信可直接预览） |
| 03 | `03_TeaWindow_Demo_EN.mp4` | 0.92 MB | 英文演示视频（2:48，30fps） |

## 怎么发微信

- **PPT**：发 `.pdf`（微信内直接预览，不依赖 Office）；需要编辑时再发 `.pptx`
- **视频**：直接发 `.mp4`（微信内可播放）
- 两份 PDF 均已内嵌团队页（第 2 页）与架构页（第 14 页），不需要单独发图

## 规格

- PPT：14 页（12 页正文 + 团队页 + 1+5 架构），< 30 MB
- PDF：14 页，微信可直接打开
- 视频：2:48（168 s），1280×720，H.264 30fps，< 200 MB

## 本轮新增

1. **1+5 可问责链**：自研生成 → 数据体检 → StartLux 放行/事实核对 → 有界修复（≤2 轮，fail-open）
2. **数据体检**：新鲜度 / 空洞 / 漂移 / 刷新 / 血缘 → score
3. **预测辅助**：`/api/forecast/assist`（霜型 / 置信 / 一致性，不改数值）
4. **霜型实验**：1,033 个霜冻日，分组订正 MAE 1.00→1.03，**主动不上线**
5. **工程**：155 tests；冻结评估集 AUC 0.998 / F1 0.85 不变

## 不要提交

- 密钥（`key.md` / `.env`）
- `report/judge_sim*.md`（内部自查）
- 原始数据与中间产物
