"""校验 ONNX 意图模型的准确率（fp32 / int8），供部署前确认。"""
import argparse
import json
import os

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_intent_tiny"))
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.model)
    classes = json.load(open(os.path.join(a.model, "labels.json"), encoding="utf-8"))["classes"]
    ev = [json.loads(l) for l in open(os.path.join(a.data, "intents_eval.jsonl"), encoding="utf-8") if l.strip()]
    texts, true = [r["text"] for r in ev], np.array([r["intent"] for r in ev])

    def acc(path):
        s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        names = [i.name for i in s.get_inputs()]
        pred = []
        for i in range(0, len(texts), 64):
            e = tok(texts[i:i + 64], truncation=True, max_length=32, padding=True)
            feed = {"input_ids": np.array(e["input_ids"], dtype=np.int64),
                    "attention_mask": np.array(e["attention_mask"], dtype=np.int64)}
            if "token_type_ids" in names:
                feed["token_type_ids"] = np.array(e.get("token_type_ids", [[0] * len(x) for x in e["input_ids"]]), dtype=np.int64)
            pred += list(s.run(None, feed)[0].argmax(-1))
        return float((np.array([classes[i] for i in pred]) == true).mean())

    for f in ("model.onnx", "model.int8.onnx"):
        p = os.path.join(a.model, f)
        if os.path.exists(p):
            print(f, f"acc={acc(p):.4f}", f"{os.path.getsize(p)//1024//1024}MB")


if __name__ == "__main__":
    main()