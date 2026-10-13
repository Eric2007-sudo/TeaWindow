"""
M3 GPU：在 D2T 数据上微调 Qwen2.5-0.5B-Instruct（全参，chat 格式，仅对 assistant 计算 loss）。
用法：
  HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 CUDA_VISIBLE_DEVICES=0 \
  ~/teacloud/envs/qa/bin/python train_d2t.py --data ~/teacloud/data/d2t --out ~/teacloud/models/qa_d2t
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
        msgs = self.rows[i]["messages"]
        prompt = self.tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
        full = self.tok.apply_chat_template(msgs, tokenize=False)
        p = self.tok(prompt, truncation=True, max_length=MAXLEN)
        f = self.tok(full, truncation=True, max_length=MAXLEN)
        ids = f["input_ids"]; lab = list(ids)
        for j in range(min(len(p["input_ids"]), len(lab))):
            lab[j] = -100
        return {"input_ids": ids, "labels": lab, "attention_mask": f["attention_mask"]}


def collate(batch, pad):
    L = max(len(b["input_ids"]) for b in batch)
    def padto(x, v): return x + [v] * (L - len(x))
    ids = torch.tensor([padto(b["input_ids"], pad) for b in batch])
    lab = torch.tensor([padto(b["labels"], -100) for b in batch])
    am = torch.tensor([padto(b["attention_mask"], 0) for b in batch])
    return ids, lab, am


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data/d2t"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_d2t"))
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--acc", type=int, default=4)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dt = torch.bfloat16 if dev == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=dt, trust_remote_code=True).to(dev)
    tr = load(os.path.join(a.data, "train.jsonl"))
    ev = load(os.path.join(a.data, "eval.jsonl"))
    dl = DataLoader(SFT(tr, tok), batch_size=a.bs, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id))
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)
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

    # 生成 3 条样例，落盘查看
    model.eval()
    with open(os.path.join(a.out, "samples.txt"), "w", encoding="utf-8") as f:
        for r in ev[:3]:
            msgs = r["messages"]
            prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
            enc = tok(prompt, return_tensors="pt").to(dev)
            out = model.generate(**enc, max_new_tokens=160, do_sample=False)
            gen = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
            f.write("USER:" + msgs[1]["content"] + "\nGOLD:" + msgs[2]["content"] + "\nPRED:" + gen + "\n\n")
    print("saved ->", a.out)


if __name__ == "__main__":
    main()
