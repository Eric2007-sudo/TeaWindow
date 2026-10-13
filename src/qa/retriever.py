"""
可选检索后端（RAG 思路）：用 GPU 微调的 BGE 嵌入（int8 ONNX）在"种子问句索引"上做近邻检索。
- 对分类低置信/疑似域外的问题，用近邻意图做**召回恢复**或**澄清候选**（意图+澄清范式）。
- 未启用（依赖缺失/文件缺失）时返回 None，引擎照常走分类器。
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
_error = None
_step = "init"


def _embed(texts):
    """分批编码 + 平均池化 + L2 归一化（与导出模型一致）。"""
    out = []
    names = [i.name for i in _session.get_inputs()]
    for i in range(0, len(texts), 64):
        encs = _tokenizer.encode_batch(texts[i:i + 64])
        feed = {"input_ids": np.array([e.ids for e in encs], dtype="int64"),
                "attention_mask": np.array([e.attention_mask for e in encs], dtype="int64")}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array([e.type_ids for e in encs], dtype="int64")
        out.append(_session.run(None, feed)[0].astype("float64"))
    z = np.concatenate(out, axis=0)
    z /= (np.linalg.norm(z, axis=1, keepdims=True) + 1e-9)
    return z


def _load():
    global _session, _tokenizer, _index, _loaded, _backend, _error, _step
    if _loaded:
        return
    _loaded = True
    _step = "enter"
    if os.environ.get("TW_RETRIEVER") == "0":
        _step = "disabled"
        return
    d = os.environ.get("TW_RETRIEVER_DIR") or DEFAULT_DIR
    mp = os.path.join(d, "model.int8.onnx")
    tp = os.path.join(d, "tokenizer.json")
    if not (os.path.exists(mp) and os.path.exists(tp) and os.path.exists(INDEX_PATH)):
        _error = (f"missing files: onnx={os.path.exists(mp)} tok={os.path.exists(tp)} "
                  f"idx={os.path.exists(INDEX_PATH)} ({d})")
        _step = "missing"
        return
    try:
        import onnxruntime as ort  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415
        _step = "tokenizer"
        tok = Tokenizer.from_file(tp)
        tok.enable_truncation(max_length=32)
        tok.enable_padding(length=32)
        _step = "session"
        sess = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
        _step = "index"
        idx = [json.loads(l) for l in open(INDEX_PATH, encoding="utf-8") if l.strip()]
        _tokenizer, _session, _index = tok, sess, idx
        _backend = "bge-small-zh-int8"
        _step = "ready"
    except BaseException as e:  # noqa: BLE001
        import traceback
        _error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _step = "error:" + _step
        print("[retriever] 检索后端不可用:", e)


def _index_vectors():
    """惰性计算索引向量（首次 nearest 时）。"""
    global _Z
    if _Z is None and _session is not None and _index:
        _Z = _embed([r["text"] for r in _index])
    return _Z


def available():
    _load()
    return _session is not None


def backend():
    _load()
    return _backend


def error():
    _load()
    return _error


def debug():
    _load()
    return {"loaded": _loaded, "backend": _backend, "error": _error, "step": _step,
            "session": _session is not None, "index": (len(_index) if _index else 0),
            "vectors_ready": _Z is not None, "env": os.environ.get("TW_RETRIEVER"),
            "dir": os.environ.get("TW_RETRIEVER_DIR") or DEFAULT_DIR}


def nearest(text, k=3):
    _load()
    if _session is None:
        return None
    try:
        Z = _index_vectors()
        z = _embed([text])[0]
        sims = Z @ z
        order = np.argsort(-sims)[:k]
        return [{"intent": _index[i]["intent"], "text": _index[i]["text"], "sim": float(sims[i])} for i in order]
    except BaseException as e:  # noqa: BLE001
        print("[retriever] 检索失败:", e)
        return None


if __name__ == "__main__":
    print("available:", available(), "backend:", backend())
    for q in ["今天有风险吗", "帮我写代码", "要不要防冻", "股票怎么样"]:
        print(q, "->", nearest(q, 3))