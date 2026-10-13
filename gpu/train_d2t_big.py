"""
M3+ 更大基座：Qwen2.5-1.5B-Instruct 部分微调（冻结主干，仅训末尾 K 层 + lm_head + norm）。
适配显存受限（共享 GPU）。用 chat 格式，仅对 assistant 计算 loss。
用法：
  HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 CUDA_VISIBLE_DEVICES=1 \
  ~/teacloud/envs/qa/bin/python train_d2t_big.py --unfreeze 6 --epochs 2 --bs 2 --acc 8
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import torch  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

MAXLEN = 512


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class SFT(Dataset):
    def __init__(self, rows, tok):
        self.rows, self.tok = rows, tok

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        m = self.rows[i]["messages"]
        prompt = self.tok.apply_chat_template(m[:-1], tokenize=False, add_generation_prompt=True)
        full = self.tok.apply_chat_template(m, tokenize=False)
        p = self.tok(prompt, truncation=True, max_length=MAXLEN)
        f = self.tok(full, truncation=True, max_length=MAXLEN)
        lab = list(f["input_ids"])
        for j in range(min(len(p["input_ids"]), len(lab))):
            lab[j] = -100
        return {"input_ids": f["input_ids"], "labels": lab, "attention_mask": f["attention_mask"]}


def collate(b, pad):
    L = max(len(x["input_ids"]) for x in b)
    def pt(x, v): return x + [v] * (L - len(x))
    return (torch.tensor([pt(x["input_ids"], pad) for x in b]),
            torch.tensor([pt(x["labels"], -100) for x in b]),
            torch.tensor([pt(x["attention_mask"], 0) for x in b]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data/d2t"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_d2t_15b"))
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--unfreeze", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--bs", type=int, default=2)
    ap.add_argument("--acc", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--maxlen", type=int, default=384)
    a = ap.parse_args()
    global MAXLEN
    MAXLEN = a.maxlen
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16).to(dev)
    for p in model.parameters():
        p.requires_grad = False
    for lyr in model.model.layers[-a.unfreeze:]:
        for p in lyr.parameters():
            p.requires_grad = True
    for n in (model.model.norm, model.lm_head):
        for p in n.parameters():
            p.requires_grad = True
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable()
    trainable = [p for p in model.parameters() if p.requires_grad]
    print(f"trainable params: {sum(p.numel() for p in trainable)/1e6:.0f}M", flush=True)
    tr = load(os.path.join(a.data, "train.jsonl"))
    dl = DataLoader(SFT(tr, tok), batch_size=a.bs, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id))
    opt = torch.optim.AdamW(trainable, lr=a.lr)
    model.train()
    step = 0
    for ep in range(a.epochs):
        tot = 0.0
        for ids, lab, am in dl:
            ids, lab, am = ids.to(dev), lab.to(dev), am.to(dev)
            out = model(input_ids=ids, attention_mask=am, labels=lab)
            (out.loss / a.acc).backward()
            if (step := step + 1) % a.acc == 0:
                opt.step(); opt.zero_grad()
            tot += out.loss.item()
        print(f"epoch {ep+1}/{a.epochs} loss {tot/len(dl):.4f}", flush=True)
        os.makedirs(a.out, exist_ok=True)
        model.save_pretrained(a.out); tok.save_pretrained(a.out)
        print("saved ->", a.out, flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
