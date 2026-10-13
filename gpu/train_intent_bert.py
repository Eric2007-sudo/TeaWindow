"""
GPU 训练（Tier2）：微调中文 BERT 做意图分类（我们自己的模型）。
用法（在 GPU 盒 ~/teacloud 内）：
  export HF_ENDPOINT=https://hf-mirror.com
  ~/teacloud/envs/qa/bin/python train_intent_bert.py --data ~/teacloud/data --out ~/teacloud/models/qa_intent_bert
"""
import argparse
import json
import os
import random

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class DS(Dataset):
    def __init__(self, rows, tok, cidx, maxlen=32):
        self.rows, self.tok, self.cidx, self.maxlen = rows, tok, cidx, maxlen

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        enc = self.tok(r["text"], truncation=True, max_length=self.maxlen, padding="max_length", return_tensors="pt")
        return {k: v.squeeze(0) for k, v in enc.items()}, self.cidx[r["intent"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_intent_bert"))
    ap.add_argument("--model", default="bert-base-chinese")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-5)
    a = ap.parse_args()

    tr = load(os.path.join(a.data, "intents_train.jsonl"))
    ev = load(os.path.join(a.data, "intents_eval.jsonl"))
    classes = sorted({r["intent"] for r in tr})
    cidx = {c: i for i, c in enumerate(classes)}
    print(f"classes={len(classes)} train={len(tr)} eval={len(ev)}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=len(classes)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)
    lossf = torch.nn.CrossEntropyLoss()
    dl = DataLoader(DS(tr, tok, cidx), batch_size=a.bs, shuffle=True)

    model.train()
    for ep in range(a.epochs):
        tot = 0.0
        for x, y in dl:
            x = {k: v.to(dev) for k, v in x.items()}; y = y.to(dev)
            opt.zero_grad()
            out = model(**x); loss = lossf(out.logits, y)
            loss.backward(); opt.step(); tot += loss.item()
        print(f"epoch {ep+1}/{a.epochs} loss {tot/len(dl):.4f}")

    # 评测
    model.eval(); correct = 0
    with torch.no_grad():
        for x, y in DataLoader(DS(ev, tok, cidx), batch_size=64):
            x = {k: v.to(dev) for k, v in x.items()}
            p = model(**x).logits.argmax(1).cpu().numpy()
            correct += int((p == y.numpy()).sum())
    acc = correct / len(ev)
    print(f"EVAL_ACC={acc:.4f}")

    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    json.dump({"classes": classes, "eval_acc": acc, "model": a.model, "n_train": len(tr), "n_eval": len(ev)},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"saved -> {a.out}")


if __name__ == "__main__":
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    main()
