"""
可选检索后端（RAG 思路）：用 GPU 蒸馏/微调的 BGE 嵌入（int8 ONNX）在"种子问句索引"上做近邻检索。
用途：
- 对分类低置信或疑似域外的问题，用检索到的近邻意图做**回退/澄清**（意图+澄清范式）；
- 未启用时返回 None，引擎照常走分类器。
模型目录：models/qa_embedder_onnx/{model.int8.onnx, tokenizer.json}；索引：data/qa/intents_index.jsonl。
"""
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DIR = os.path.join(ROOT, "models", "qa_embedder_onnx")
INDEX_PATH = os.path.join(ROOT, "data", "qa", "intents_index.jsonl")

_session = None
_tokenizer = None
_index = None
_Z = None
_loaded = False
_backend = None


def _pool(ids, mask):
    # 简化：以 token 平均（受 padding 影响小，因 mask 处理）
    return None


def _embed(texts):
    encs = _tokenizer.encode_batch(texts)
    ids = np.array([e.ids for e in encs], dtype="int64")
    mask = np.array([e.attention_mask for e in encs], dtype="int64")
    names = [i.name for i in _session.get_inputs()]
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in names:
        feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype="int64")
    z = _session.run(None, feed)[0].astype("float64")
    z /= (np.linalg.norm(z, axis=1, keepdims=True) + 1e-9)
    return z


def _load():
    global _session, _tokenizer, _index, _Z, _loaded, _backend
    if _loaded:
        return
    _loaded = True
    if os.environ.get("TW_RETRIEVER") == "0":
        return
    d = os.environ.get("TW_RETRIEVER_DIR") or DEFAULT_DIR
    mp = os.path.join(d, "model.int8.onnx")
    tp = os.path.join(d, "tokenizer.json")
    if not (os.path.exists(mp) and os.path.exists(tp) and os.path.exists(INDEX_PATH)):
        return
    try:
        import onnxruntime as ort  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415
        tok = Tokenizer.from_file(tp)
        tok.enable_truncation(max_length=32)
        tok.enable_padding(length=32)
        sess = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
        _tokenizer, _session = tok, sess
        _index = [json.loads(l) for l in open(INDEX_PATH, encoding="utf-8") if l.strip()]
        _Z = _embed([r["text"] for r in _index])
        _backend = "bge-small-zh-int8"
        print("[retriever] 检索后端已启用:", _backend, "索引", len(_index))
    except Exception as e:  # noqa: BLE001
        print("[retriever] 检索后端不可用:", e)


def available():
    _load()
    return _Z is not None


def backend():
    _load()
    return _backend


def nearest(text, k=3):
    _load()
    if _Z is None:
        return None
    z = _embed([text])[0]
    sims = _Z @ z
    order = np.argsort(-sims)[:k]
    return [{"intent": _index[i]["intent"], "text": _index[i]["text"], "sim": float(sims[i])} for i in order]


if __name__ == "__main__":
    print("available:", available())
    for q in ["今天有风险吗", "帮我写代码", "要不要防冻", "股票怎么样"]:
        print(q, "->", nearest(q, 3))