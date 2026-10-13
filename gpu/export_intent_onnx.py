"""GPU：把微调后的意图分类 BERT 导出为 ONNX 并做动态 int8 量化，用 onnxruntime 校验与 PyTorch 一致。
用法：
  CUDA_VISIBLE_DEVICES=1 ~/teacloud/envs/qa/bin/python export_intent_onnx.py \
    --model ~/teacloud/models/qa_intent_bert2 --out ~/teacloud/models/qa_intent_onnx
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_intent_bert2"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_intent_onnx"))
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).eval().to("cpu")
    classes = json.load(open(os.path.join(a.model, "labels.json"), encoding="utf-8"))["classes"]

    dummy = tok("今天有风险吗", return_tensors="pt")
    args = (dummy["input_ids"], dummy["attention_mask"], dummy.get("token_type_ids", torch.zeros_like(dummy["input_ids"])))
    onnx_path = os.path.join(a.out, "model.onnx")
    kw = dict(input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["logits"],
              dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                            "token_type_ids": {0: "b", 1: "s"}, "logits": {0: "b"}}, opset_version=17)
    try:
        torch.onnx.export(model, args, onnx_path, dynamo=False, **kw)
    except TypeError:
        torch.onnx.export(model, args, onnx_path, **kw)
    tok.save_pretrained(a.out)
    print("exported", onnx_path, os.path.getsize(onnx_path) // 1024 // 1024, "MB", flush=True)

    from onnxruntime.quantization import QuantType, quantize_dynamic
    qpath = os.path.join(a.out, "model.int8.onnx")
    quantize_dynamic(onnx_path, qpath, weight_type=QuantType.QInt8)
    print("int8", qpath, os.path.getsize(qpath) // 1024 // 1024, "MB", flush=True)

    ev = [json.loads(l) for l in open(os.path.join(a.data, "intents_eval.jsonl"), encoding="utf-8") if l.strip()]
    texts = [r["text"] for r in ev]
    ytrue = np.array([r["intent"] for r in ev])
    with torch.no_grad():
        enc = tok(texts, truncation=True, max_length=32, padding=True, return_tensors="pt")
        tp = model(**enc).logits.argmax(-1).numpy()

    def ort_preds(path):
        s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        names = [i.name for i in s.get_inputs()]
        out = []
        for i in range(0, len(texts), 32):
            e = tok(texts[i:i + 32], truncation=True, max_length=32, padding=True)
            feed = {"input_ids": np.array(e["input_ids"], dtype=np.int64),
                    "attention_mask": np.array(e["attention_mask"], dtype=np.int64)}
            if "token_type_ids" in names:
                feed["token_type_ids"] = np.array(e.get("token_type_ids", [[0] * len(x) for x in e["input_ids"]]), dtype=np.int64)
            out += list(s.run(None, feed)[0].argmax(-1))
        return np.array(out)

    report = {}
    for path in (onnx_path, qpath):
        p = ort_preds(path)
        acc = float((np.array([classes[i] for i in p]) == ytrue).mean())
        agree = float((p == tp).mean())
        report[os.path.basename(path)] = {"acc": acc, "agree_torch": agree}
        print(os.path.basename(path), f"acc={acc:.4f}", f"agree_torch={agree:.4f}", flush=True)
    json.dump({"model": a.model, "classes": classes, "n_eval": len(ev), "verify": report},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("DONE")


if __name__ == "__main__":
    main()