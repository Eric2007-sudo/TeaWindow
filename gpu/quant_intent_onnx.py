"""尝试多种 ONNX 动态量化配置，选精度最好的 int8（供部署）。"""
import argparse
import json
import os
import shutil

import numpy as np
import onnxruntime as ort
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoTokenizer


def acc(path, tok, classes, rows):
    s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    names = [i.name for i in s.get_inputs()]
    pred = []
    texts = [r["text"] for r in rows]
    for i in range(0, len(texts), 64):
        e = tok(texts[i:i + 64], truncation=True, max_length=32, padding=True)
        feed = {"input_ids": np.array(e["input_ids"], dtype=np.int64),
                "attention_mask": np.array(e["attention_mask"], dtype=np.int64)}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array(e.get("token_type_ids", [[0] * len(x) for x in e["input_ids"]]), dtype=np.int64)
        pred += list(s.run(None, feed)[0].argmax(-1))
    return float((np.array([classes[i] for i in pred]) == np.array([r["intent"] for r in rows])).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_intent_rbt3_oos"))
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    a = ap.parse_args()
    d = a.model
    tok = AutoTokenizer.from_pretrained(d)
    classes = json.load(open(os.path.join(d, "labels.json"), encoding="utf-8"))["classes"]
    rows = [json.loads(l) for l in open(os.path.join(a.data, "intents_eval.jsonl"), encoding="utf-8") if l.strip()]
    fp = os.path.join(d, "model.onnx")
    print("fp32 acc", round(acc(fp, tok, classes, rows), 4), os.path.getsize(fp) // 1024 // 1024, "MB", flush=True)
    cfgs = [
        ("QInt8", dict(weight_type=QuantType.QInt8)),
        ("QInt8_pc", dict(weight_type=QuantType.QInt8, per_channel=True)),
        ("QInt8_rr", dict(weight_type=QuantType.QInt8, reduce_range=True)),
        ("QUInt8", dict(weight_type=QuantType.QUInt8)),
        ("QUInt8_pc", dict(weight_type=QuantType.QUInt8, per_channel=True)),
    ]
    best = (None, -1, None)
    for name, kw in cfgs:
        out = os.path.join(d, f"model.try_{name}.onnx")
        try:
            quantize_dynamic(fp, out, **kw)
        except Exception as e:  # noqa: BLE001
            print(name, "量化失败:", e, flush=True)
            continue
        ac = acc(out, tok, classes, rows)
        sz = os.path.getsize(out) // 1024 // 1024
        print(f"{name} acc={ac:.4f} {sz}MB", flush=True)
        if ac > best[1]:
            best = (name, ac, out)
    print("BEST", best[0], round(best[1], 4), flush=True)
    if best[2]:
        shutil.copy(best[2], os.path.join(d, "model.int8.onnx"))
        print("saved best ->", os.path.join(d, "model.int8.onnx"), flush=True)
    for name, _ in cfgs:
        p = os.path.join(d, f"model.try_{name}.onnx")
        if os.path.exists(p):
            os.remove(p)


if __name__ == "__main__":
    main()