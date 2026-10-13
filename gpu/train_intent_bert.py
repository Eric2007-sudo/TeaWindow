"""
GPU 训练（Tier2）：微调中文编码器做意图分类（我们自己的模型）。
特性：按 epoch 评测 + **早停**（防过拟合）+ 独立**挑战集**评测（测泛化）。
用法（在 GPU 盒 ~/teacloud 内）：
  CUDA_VISIBLE_DEVICES=1 ~/teacloud/envs/qa/bin/python train_intent_bert.py \
    --data ~/teacloud/data --out ~/teacloud/models/qa_intent_bert3 --model hfl/chinese-roberta-wwm-ext --epochs 10 --patience 3
"""
import argparse
import json
import os
import random
import copy

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import torch  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


class DS(Dataset):
    def __init__(self, rows, tok, cidx, maxlen=32):
        self.rows, self.tok, self.cidx, self.maxlen = rows, tok, cidx, maxlen

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        enc = self.tok(r["text"], truncation=True, max_length=self.maxlen, padding="max_length", return_tensors="pt")
        return {k: v.squeeze(0) for k, v in enc.items()}, self.cidx[r["intent"]]


def predict(model, tok, rows, cidx, dev, bs=128, maxlen=32):
    model.eval(); correct = 0; idx2c = {v: k for k, v in cidx.items()}
    with torch.no_grad():
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            e = tok([r["text"] for r in chunk], truncation=True, max_length=maxlen, padding=True, return_tensors="pt")
            e = {k: v.to(dev) for k, v in e.items()}
            p = model(**e).logits.argmax(1).cpu().numpy()
            correct += int(sum(1 for j, r in enumerate(chunk) if idx2c[int(p[j])] == r["intent"]))
    model.train()
    return correct / max(1, len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_intent_bert3"))
    ap.add_argument("--model", default="bert-base-chinese")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--wd", type=float, default=0.01)
    a = ap.parse_args()

    tr = load(os.path.join(a.data, "intents_train.jsonl"))
    ev = load(os.path.join(a.data, "intents_eval.jsonl"))
    ch = load(os.path.join(a.data, "intents_challenge.jsonl"))
    classes = sorted({r["intent"] for r in tr})
    cidx = {c: i for i, c in enumerate(classes)}
    print(f"classes={len(classes)} train={len(tr)} eval={len(ev)} challenge={len(ch)} base={a.model}", flush=True)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForSequenceClassification.from_pretrained(a.model, num_labels=len(classes)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd)
    lossf = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
    dl = DataLoader(DS(tr, tok, cidx), batch_size=a.bs, shuffle=True)

    best_acc = -1.0; best_state = None; best_ep = 0; bad = 0
    for ep in range(a.epochs):
        model.train(); tot = 0.0
        for x, y in dl:
            x = {k: v.to(dev) for k, v in x.items()}; y = y.to(dev)
            opt.zero_grad()
            out = model(**x); loss = lossf(out.logits, y)
            loss.backward(); opt.step(); tot += loss.item()
        ev_acc = predict(model, tok, ev, cidx, dev)
        ch_acc = predict(model, tok, ch, cidx, dev) if ch else float("nan")
        print(f"epoch {ep+1}/{a.epochs} loss {tot/len(dl):.4f} eval_acc {ev_acc:.4f} challenge_acc {ch_acc:.4f}", flush=True)
        if ev_acc > best_acc + 1e-6:
            best_acc, best_ep, bad = ev_acc, ep + 1, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            bad += 1
            if bad >= a.patience:
                print(f"early stop at epoch {ep+1} (best epoch {best_ep} eval_acc {best_acc:.4f})", flush=True)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    ev_acc = predict(model, tok, ev, cidx, dev)
    ch_acc = predict(model, tok, ch, cidx, dev) if ch else float("nan")
    print(f"BEST eval_acc={ev_acc:.4f} challenge_acc={ch_acc:.4f} (best_epoch={best_ep})", flush=True)

    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    json.dump({"classes": classes, "eval_acc": ev_acc, "challenge_acc": ch_acc, "base_model": a.model,
               "n_train": len(tr), "n_eval": len(ev), "n_challenge": len(ch), "best_epoch": best_ep},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"saved -> {a.out}", flush=True)


if __name__ == "__main__":
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    main()