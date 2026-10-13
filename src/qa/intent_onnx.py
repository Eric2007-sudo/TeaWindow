"""
可选意图分类后端：ONNX（GPU 蒸馏的 rbt3 学生模型，int8 量化）。
- 若 `onnxruntime` 与 `tokenizers` 可用且模型文件存在，则启用；否则返回 None，由 numpy 模型兜底。
- 用法：engine.classify() 会优先调用本模块；`TW_INTENT_ONNX` 可覆盖模型目录，`TW_INTENT_ONNX=0` 可禁用。
模型目录（默认 `models/qa_intent_onnx/`）：{model.int8.onnx, tokenizer.json, labels.json}
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DIR = os.path.join(ROOT, "models", "qa_intent_onnx")

_session = None
_tokenizer = None
_classes = None
_loaded = False
_backend = None


def _load():
    global _session, _tokenizer, _classes, _loaded, _backend
    if _loaded:
        return
    _loaded = True
    if os.environ.get("TW_INTENT_ONNX") == "0":
        return
    d = os.environ.get("TW_INTENT_ONNX") or DEFAULT_DIR
    mp = os.path.join(d, "model.int8.onnx")
    tp = os.path.join(d, "tokenizer.json")
    lp = os.path.join(d, "labels.json")
    if not (os.path.exists(mp) and os.path.exists(tp) and os.path.exists(lp)):
        return
    try:
        import onnxruntime as ort  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415
        tok = Tokenizer.from_file(tp)
        tok.enable_truncation(max_length=32)
        tok.enable_padding(length=32)
        sess = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
        _tokenizer, _session = tok, sess
        _classes = json.load(open(lp, encoding="utf-8"))["classes"]
        _backend = "onnx-rbt3-int8"
        print("[intent] ONNX 后端已启用:", _backend)
    except Exception as e:  # noqa: BLE001
        print("[intent] ONNX 后端不可用，使用 numpy 兜底:", e)


def available():
    _load()
    return _session is not None


def backend():
    _load()
    return _backend


def classify(text):
    """返回 (label, confidence) 或 None（未启用/失败）。"""
    _load()
    if _session is None:
        return None
    try:
        import numpy as np
        enc = _tokenizer.encode(text)
        feed = {"input_ids": np.array([enc.ids], dtype="int64"),
                "attention_mask": np.array([enc.attention_mask], dtype="int64")}
        names = [i.name for i in _session.get_inputs()]
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array([enc.type_ids], dtype="int64")
        logits = _session.run(None, feed)[0][0].astype("float64")
        logits -= logits.max()
        p = np.exp(logits)
        p /= p.sum()
        i = int(p.argmax())
        return _classes[i], float(p[i])
    except Exception as e:  # noqa: BLE001
        print("[intent] ONNX 推理失败，本次回退:", e)
        return None


if __name__ == "__main__":
    print("available:", available(), "backend:", backend())
    for q in ["今天有风险吗", "明天要不要防冻", "先采哪块地", "保险多少钱一亩", "今年什么时候开采"]:
        print(q, "->", classify(q))