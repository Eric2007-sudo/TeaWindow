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

## 5. 蒸馏实验（诚实结论）
尝试把 BERT 的伪标签蒸馏进生产 numpy 模型（**失败**），但**蒸馏到小 transformer 学生模型成功**：

### 5.1 伪标签蒸馏进 numpy（失败）
| 伪标签来源 | 蒸馏后 numpy 准确率 |
|---|---|
| 噪声增广（含字符删改） | 50.0% |
| 干净增广（仅前缀/后缀/同义） | 52.7% |
- 现象：训练 loss 更低、评测更差 → **过拟合伪标签噪声**；小语料下线性模型蒸馏收益不稳定。
- 处理：**弃用**（`.bak` 保留），生产 numpy 模型回到 75.7% 的未蒸馏版本。

### 5.2 蒸馏到 tiny 学生（成功，可部署）
`gpu/distill_intent_tiny.py`：教师 `qa_intent_bert2`（91.9%）→ 学生 `ckiplab/bert-tiny-chinese`，
硬标签 CE + 教师软标签 KD（含 4000 条干净增广问句），12 epochs。

| 模型 | 评测准确率 | 体积 |
|---|---|---|
| 教师 BERT（bert-base-chinese） | 91.9% | 390 MB fp32 / 98 MB int8 |
| **学生 tiny（bert-tiny-chinese）** | **90.5%** | 44 MB fp32 / **11 MB int8** |
| 学生 int8 ONNX（onnxruntime 实测） | **0.9054** | **11 MB** |
| numpy 生产模型（对照） | 75.7% | <2 MB |

- 结论：**用约 1/9 的体积几乎保住教师精度（-1.4pt）**，且 **int8 无额外精度损失**；
  11 MB 的 int8 ONNX 具备**上 Render 免费层**的体积条件（仍需 tokenizer 与 onnxruntime，见 §6）。
- 产物：`~/teacloud/models/qa_intent_tiny/{model.onnx,model.int8.onnx}`；校验脚本 `gpu/verify_onnx_intent.py`。

## 5b. 语义嵌入（本轮重训）
在新语料上重训 `bge-small-zh-v1.5`（15 epochs，对比学习）：

| 指标 | 旧语料 | 新语料 |
|---|---|---|
| 近邻检索意图准确率 | 77.1% | **83.8%** |

## 6. 部署取舍
- **Render/离线（当前生产）**：numpy 轻量意图模型（75.7%）+ **强关键词/兜底规则**（对灾害类问题强关键词优先，实际可用性高于单看分类准确率）。
- **可选增强（已具备产物）**：
  - `qa_intent_tiny` int8 ONNX（**90.5%，11 MB**）：体积满足免费层条件，但仍需 `onnxruntime` 与 WordPiece 分词；
  - `qa_intent_bert2`（91.9%）与 `qa_intent_onnx`（fp32 91.9% / int8 89.2%）：GPU/边缘端使用。
- 备注：`onnxruntime` + 分词器依赖较重，是否接入生产需权衡冷启动与构建体积；如需接入，建议用 `int8 tiny`。

## 7. 产物与来源
- 权重：`~/teacloud/models/{qa_intent_bert2,qa_intent_onnx,qa_intent_tiny,qa_embedder}`。
- 校验：`gpu/verify_onnx_intent.py`（int8 tiny = 0.9054）。
- 日志：`report/gpu_train_intent2.txt`、`report/gpu_export_intent_onnx.txt`、`report/gpu_distill_tiny.txt`、`report/gpu_train_embedder2.txt`、
  `report/gpu_intent_onnx_labels.json`、`report/gpu_intent_tiny_labels.json`。
- 本报告数字均由上述脚本在 GPU 1 上实测得到；GPU 已于训练后释放。

## 8. 第四轮（扩语料 + 更强基座 + 蒸馏上线）
> 目标：按"适当增大训练/测试集、防过拟合"的要求再训一轮，并把最优学生模型接入生产。

### 8.1 语料再扩（分层 + 独立挑战集）
| 项 | 第三轮 | 第四轮 |
|---|---|---|
| 训练样本 | 1561 | **2051** |
| 评测样本 | 74 | **125**（每类 ≥5，分层） |
| 挑战集（手写、不参与训练） | — | **45** |

### 8.2 教师：`hfl/chinese-roberta-wwm-ext`（早停）
| 指标 | 值 |
|---|---|
| 评测准确率 | **93.6%** |
| 挑战集准确率 | **88.9%** |
| 最佳 epoch | 2（patience=3 早停，防过拟合） |

### 8.3 学生蒸馏对比
| 学生 | 评测 | 挑战集 | 体积(int8) | 结论 |
|---|---|---|---|---|
| `ckiplab/bert-tiny-chinese` | 84.0% | 68.9% | 11 MB | 容量不足，泛化差 |
| **`hfl/rbt3`** | **92.8%** | **91.1%** | **36 MB** | **接近教师、泛化更好 → 采用** |
| numpy 生产模型 | 76.8% | 82.2% | <2 MB | 兜底 |

- `hfl/rbt3` int8 ONNX（onnxruntime 实测）：**评测 91.2%**，36 MB；早停于 epoch 1，几乎无过拟合。
- 关键：**换更强教师 + 更大且分层的语料**后，学生不再是瓶颈（tiny→rbt3 提升 8.8pt）。

### 8.4 上线（生产可选后端）
- 新增 `src/qa/intent_onnx.py`：**优先调用 ONNX（rbt3-int8）**，依赖缺失或失败**自动回退 numpy**（`TW_INTENT_ONNX=0` 可禁用）。
- 模型入仓：`models/qa_intent_onnx/{model.int8.onnx(36MB), tokenizer.json, labels.json, vocab.txt}`；
  `requirements.txt` 增 `onnxruntime`、`tokenizers`。
- `/api/ask` 响应新增 `backend` 字段（`onnx-rbt3-int8` 或 `numpy`）。
- 校验：`tests/test_eval2.py` 覆盖后端可用性、类别一致与**回退路径**。

## 9. 第五轮：开源范式落地（OOS K+1 / RAG 思路 / Guardrails）
> 先上网调研开源问答训练范式，再据此训练。参考：EMNLP'24《Searching for Best Practices in RAG》（查询分类→检索、混合检索、重排）、
> QLoRA 论文与 LoRA/QLoRA 实践（参数高效微调）、EACL'26《Intent Classification with Clarification》与 OOS 数据集论文（K+1/软标签/fallback 阈值）、
> NeMo Guardrails（hallucination rail / fallback）。

### 9.1 显式域外类（OOS，K+1）
- 在 15 类基础上新增 **`oos` 类**（域外：医疗/金融/编程/闲聊/乱码/英文等 100+ 例），采用 **K+1 + 软标签** 思路训练。
- 引擎：命中 OOS 且无强关键词 → **明确拒答/给边界**（不再低置信硬答）。

| 模型 | 评测（146，含 oos） | 挑战集（45，域内泛化） |
|---|---|---|
| numpy 兜底（16 类） | 74.7% | 73.3% |
| **rbt3 学生 fp32（16 类）** | **94.5%** | **93.3%** |
| rbt3 学生 int8（部署） | 89.0% | — |
| 教师 RoBERTa-wwm-ext | 94.5% | 95.6% |

- 结论：加入 OOS 后域内精度不降反升（教师挑战集 88.9%→**95.6%**）；int8 有约 5.5pt 量化损失（受新增 OOS 边界影响），仍显著优于 numpy。

### 9.2 RAG / Guardrails 思路
- **RAG 最佳实践**（查询分类→是否检索、混合检索、重排）用于指导"先判定是否为域内可答、再接地生成"的流程；本项目以**结构化事实模板 + 来源链**替代重型向量库，保证可审计。
- **Guardrails/fallback**：OOS 拒识 + 低置信澄清 + LLM 润色失败回退，等价于 hallucination rail。
- **LoRA/QLoRA**：作为后续对生成层（D2T）的参数高效微调方案记录在路线图（当前生产用规则，避免事实风险）。

### 9.3 部署
- 16 类 int8 ONNX（36MB）替换上版，`models/qa_intent_onnx/` 已更新；`/api/ask` 的 `backend` 仍为 `onnx-rbt3-int8`。