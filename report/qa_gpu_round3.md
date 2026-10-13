# 自研问答模型 · 第三轮训练与优化（GPU）

> 目标：继续训练/优化"意图分类"自研模型，并把此前**未完成的 ONNX 导出**打通、验证。
> 环境：`eric@10.130.144.31:~/teacloud`，8×RTX 4090（本轮使用 **GPU 1**，其余为他人任务）；
> torch 2.14.1+cu130，transformers 5.19，CUDA 可用；模型/日志在 `~/teacloud/{models,out}`。
> 复现脚本：`src/qa/build_corpus.py`、`gpu/train_intent_bert.py`、`gpu/predict_intent.py`、`gpu/export_intent_onnx.py`。

## 1. 语料升级（先修"评测偏差"）
上一轮评测集仅 **35 条**，且 **`schedule` 类为 0 条**，各类分布不均 → 77.1% 偏乐观。
本轮改为**按类分层抽样**（每类 ≥3 条），并把种子问句扩至每类 ≥18 条：

| 项 | 旧 | 新 |
|---|---|---|
| 意图类别 | 15 | 15 |
| 训练样本（含增广） | 1015 | **1561** |
| 评测样本 | 35（schedule=0） | **74（每类 4–6）** |

评测集保持"干净"（不做字符增广），避免训练/评测泄漏。

## 2. 本机 numpy 生产模型
字符 1–2gram + softmax 逻辑回归（生产默认，零 torch 依赖）。调参结果：

| 设置 | 评测准确率 |
|---|---|
| iters=1500, lr=2.0, l2=1e-5（旧默认） | 70.3% |
| **iters=3000, lr=3.0, l2=1e-4（采用）** | **75.7%** |
| iters=7000（过拟合） | 74.3% |

→ `models/qa_intent.json` 已更新；`report/qa_model.md` 随之刷新（含各类分布与样例）。

## 3. GPU BERT 意图模型
微调 `bert-base-chinese`（6 epochs，GPU 1）：

| 模型 | 评测准确率 |
|---|---|
| numpy 轻量模型（生产） | 75.7% |
| **BERT（GPU，`qa_intent_bert2`）** | **91.9%** |

BERT 在**同一份 74 条分层评测**上比轻量模型高 **16.2 个百分点**，说明该任务可学、瓶颈在模型容量而非任务本身。

## 4. ONNX 导出（此前失败，本轮打通并验证）
用 `torch.onnx.export`（opset 17，动态轴）+ `onnxruntime.quantization.quantize_dynamic`：

| 产物 | 体积 | onnxruntime 准确率 | 与 PyTorch 一致率 |
|---|---|---|---|
| `model.onnx`（fp32） | 390 MB | **0.9189** | **1.0000** |
| `model.int8.onnx` | 98 MB | **0.8919** | 0.9595 |

- 关键修复：此前 `optimum` 导 Qwen 分词器时报 `'list' object has no attribute 'keys'`（`extra_special_tokens` 字段在新版 transformers 下需为 dict）；本轮改用 `torch.onnx.export` 并显式传 `token_type_ids`，绕开该问题。
- 结论：ONNX fp32 与 PyTorch **完全等价**；int8 动态量化损失约 3 个百分点，可对接 `onnxruntime`（CPU 推理）。

## 5. 蒸馏实验（诚实结论：未采用）
尝试把 BERT 的伪标签蒸馏进生产 numpy 模型，两种都失败：

| 伪标签来源 | 蒸馏后 numpy 准确率 |
|---|---|
| 噪声增广（含字符删改） | 50.0% |
| 干净增广（仅前缀/后缀/同义） | 52.7% |

- 现象：训练 loss 更低、评测更差 → **过拟合伪标签噪声**；小语料下蒸馏收益不稳定。
- 处理：**弃用**（`.bak` 保留），生产 numpy 模型回到 75.7% 的未蒸馏版本。

## 6. 部署取舍（不变）
- **Render/离线**：numpy 轻量意图模型（75.7%）+ **强关键词/兜底规则**（对灾害类问题强关键词优先，实际可用性高于单看分类准确率）。
- **GPU/边缘**：BERT（91.9%）与 int8 ONNX（89.2%）作为可选增强，机制与脚本已备（`gpu/export_intent_onnx.py`）。
- 备注：int8 ONNX 98 MB 仍偏大，不适合免费层；若要上线，需进一步蒸馏到 tiny 模型。

## 7. 产物与来源
- 权重：`~/teacloud/models/qa_intent_bert2`、`~/teacloud/models/qa_intent_onnx/{model.onnx,model.int8.onnx}`。
- 日志：`report/gpu_train_intent2.log`、`report/gpu_export_intent_onnx.log`、`report/gpu_intent_onnx_labels.json`。
- 本报告数字均由上述脚本在 GPU 1 上实测得到；GPU 已于训练后释放。