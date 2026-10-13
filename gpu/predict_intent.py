"""GPU 推理：用微调后的 BERT 给（大量合成）问句打伪标签，用于蒸馏到本地轻量模型。
用法：python predict_intent.py --model ~/teacloud/models/qa_intent_bert --in ~/teacloud/data/pseudo_input.jsonl --out ~/teacloud/data/pseudo_labeled.jsonl
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_intent_bert"))
    ap.add_argument("--in", dest="inp", default=os.path.expanduser("~/teacloud/data/pseudo_input.jsonl"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/data/pseudo_labeled.jsonl"))
    ap.add_argument("--bs", type=int, default=256)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model).to(dev).eval()
    classes = json.load(open(os.path.join(a.model, "labels.json"), encoding="utf-8"))["classes"]
    texts = [json.loads(l)["text"] for l in open(a.inp, encoding="utf-8") if l.strip()]
    out = open(a.out, "w", encoding="utf-8")
    with torch.no_grad():
        for i in range(0, len(texts), a.bs):
            e = tok(texts[i:i + a.bs], truncation=True, max_length=32, padding=True, return_tensors="pt")
            e = {k: v.to(dev) for k, v in e.items()}
            logits = model(**e).logits
            prob = torch.softmax(logits, -1)
            conf, pred = prob.max(-1)
            for t, p, c in zip(texts[i:i + a.bs], pred.cpu().tolist(), conf.cpu().tolist()):
                out.write(json.dumps({"text": t, "intent": classes[p], "conf": round(c, 3)}, ensure_ascii=False) + "\n")
    out.close()
    print(f"labeled {len(texts)} -> {a.out}")


if __name__ == "__main__":
    main()
