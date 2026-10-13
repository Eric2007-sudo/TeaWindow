"""
GPU 训练（Tier2）：语义嵌入（bge-small-zh 对比学习，我们自己的检索模型）。
输出到 ~/teacloud/models/qa_embedder；并打印近邻检索评测。
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class DS(Dataset):
    def __init__(self, rows, tok, ml=32):
        self.rows, self.tok, self.ml = rows, tok, ml

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        e = self.tok(self.rows[i]["text"], truncation=True, max_length=self.ml, padding="max_length", return_tensors="pt")
        return {k: v.squeeze(0) for k, v in e.items()}


def mean_pool(last, mask):
    m = mask.unsqueeze(-1).float()
    return (last * m).sum(1) / m.sum(1).clamp(min=1e-9)


def encode(model, tok, texts, dev, bs=64):
    model.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(texts), bs):
            e = tok(texts[i:i + bs], truncation=True, max_length=32, padding=True, return_tensors="pt")
            e = {k: v.to(dev) for k, v in e.items()}
            h = model(**e).last_hidden_state
            z = F.normalize(mean_pool(h, e["attention_mask"]), dim=-1)
            out.append(z.cpu())
    return torch.cat(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_embedder"))
    ap.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-5)
    a = ap.parse_args()

    tr = load(os.path.join(a.data, "intents_train.jsonl"))
    ev = load(os.path.join(a.data, "intents_eval.jsonl"))
    classes = sorted({r["intent"] for r in tr})
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModel.from_pretrained(a.model).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)
    dl = DataLoader(DS(tr, tok), batch_size=a.bs, shuffle=True)
    labels = [cidx for cidx in [classes.index(r["intent"]) for r in tr]]
    label_t = torch.tensor(labels)

    model.train()
    for ep in range(a.epochs):
        tot = 0.0
        for bi, x in enumerate(dl):
            x = {k: v.to(dev) for k, v in x.items()}
            idx = list(range(bi * a.bs, min((bi + 1) * a.bs, len(tr))))
            y = label_t[idx].to(dev)
            h = model(**x).last_hidden_state
            z = F.normalize(mean_pool(h, x["attention_mask"]), dim=-1)
            n = len(y)
            eye = torch.eye(n, device=dev, dtype=torch.bool)
            sim = (z @ z.t()) / 0.07
            sim = sim.masked_fill(eye, -1e9)                       # 排除自身
            pos = (y[:, None] == y[None, :]) & (~eye)              # 同类且非自身
            logp = F.log_softmax(sim, dim=1)
            denom = pos.sum(1).clamp(min=1)
            loss = -(logp * pos).sum(1) / denom
            loss = loss[torch.isfinite(loss)].mean()
            opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss)
        print(f"epoch {ep+1}/{a.epochs} loss {tot/len(dl):.4f}")

    # 近邻检索评测：eval 文本 -> 训练集中最近样本的意图
    Ztr = encode(model, tok, [r["text"] for r in tr], dev)
    Zev = encode(model, tok, [r["text"] for r in ev], dev)
    sim = Zev @ Ztr.t()
    pred = [classes[label_t[int(i)].item()] for i in sim.argmax(1)]
    acc = np.mean([p == r["intent"] for p, r in zip(pred, ev)])
    print(f"RETRIEVAL_ACC={acc:.4f}")

    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    json.dump({"model": a.model, "retrieval_acc": float(acc), "classes": classes},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"saved -> {a.out}")


if __name__ == "__main__":
    main()
