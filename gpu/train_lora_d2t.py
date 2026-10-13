"""GPU：用 LoRA/QLoRA（PEFT）对小型开源 LLM 做 D2T 微调，并报告事实数字保持率。
- 开源范式：LoRA/QLoRA 参数高效微调（Dettmers et al. QLoRA；Hu et al. LoRA）。
- 仅对 assistant 段计算 loss；评测用"事实数字是否原样出现"衡量接地度。
用法：
  CUDA_VISIBLE_DEVICES=1 ~/teacloud/envs/qa/bin/python train_lora_d2t.py \
    --model Qwen/Qwen2.5-0.5B-Instruct --out ~/teacloud/models/qa_d2t_lora --max_train 8000 --epochs 2
"""
import argparse
import json
import os
import re

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import torch  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

MAXLEN = 512


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def nums_in_facts(user):
    m = re.search(r"事实：(.*)$", user, re.S)
    if not m:
        return []
    try:
        f = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for v in f.values():
        if isinstance(v, bool):
            continue
        out += re.findall(r"\d+(?:\.\d+)?", str(v))
    return out


class SFT(Dataset):
    def __init__(self, rows, tok, maxlen=MAXLEN):
        self.rows, self.tok, self.maxlen = rows, tok, maxlen

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        m = self.rows[i]["messages"]
        prompt = self.tok.apply_chat_template(m[:-1], tokenize=False, add_generation_prompt=True)
        full = self.tok.apply_chat_template(m, tokenize=False)
        p = self.tok(prompt, truncation=True, max_length=self.maxlen)
        f = self.tok(full, truncation=True, max_length=self.maxlen)
        lab = list(f["input_ids"])
        for j in range(min(len(p["input_ids"]), len(lab))):
            lab[j] = -100
        return {"input_ids": f["input_ids"], "labels": lab, "attention_mask": f["attention_mask"]}


def collate(b, pad):
    L = max(len(x["input_ids"]) for x in b)
    pt = lambda x, v: x + [v] * (L - len(x))
    return (torch.tensor([pt(x["input_ids"], pad) for x in b]),
            torch.tensor([pt(x["labels"], -100) for x in b]),
            torch.tensor([pt(x["attention_mask"], 0) for x in b]))


@torch.no_grad()
def fact_recall(model, tok, rows, dev, n=120, max_new=140):
    model.eval()
    hit = tot = 0
    for r in rows[:n]:
        f = nums_in_facts(r["messages"][1]["content"])
        if not f:
            continue
        prompt = tok.apply_chat_template(r["messages"][:-1], tokenize=False, add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt", truncation=True, max_length=MAXLEN).to(dev)
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False)
        text = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
        for x in f:
            tot += 1
            hit += 1 if x in text else 0
    model.train()
    return hit / max(1, tot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data/d2t"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_d2t_lora"))
    ap.add_argument("--max_train", type=int, default=8000)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--bs", type=int, default=8)
    ap.add_argument("--acc", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16).to(dev)
    model.config.use_cache = False

    from peft import LoraConfig, get_peft_model
    lconf = LoraConfig(r=a.r, lora_alpha=a.alpha, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                       target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lconf)
    trn = getattr(model, "print_trainable_parameters", None)
    if trn:
        trn()

    tr = load(os.path.join(a.data, "train.jsonl"))[:a.max_train]
    ev = load(os.path.join(a.data, "eval.jsonl"))
    base_recall = fact_recall(model, tok, ev, dev)
    print(f"BASE fact_recall={base_recall:.4f}", flush=True)

    dl = DataLoader(SFT(tr, tok), batch_size=a.bs, shuffle=True, collate_fn=lambda b: collate(b, tok.pad_token_id))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    model.train(); step = 0
    for ep in range(a.epochs):
        tot = 0.0
        for ids, lab, am in dl:
            ids, lab, am = ids.to(dev), lab.to(dev), am.to(dev)
            loss = model(input_ids=ids, attention_mask=am, labels=lab).loss / a.acc
            loss.backward()
            step += 1
            if step % a.acc == 0:
                opt.step(); opt.zero_grad()
            tot += float(loss) * a.acc
        print(f"epoch {ep+1}/{a.epochs} loss {tot/len(dl):.4f}", flush=True)
    recall = fact_recall(model, tok, ev, dev)
    print(f"LORA fact_recall={recall:.4f} (base {base_recall:.4f})", flush=True)

    os.makedirs(a.out, exist_ok=True)
    model.save_pretrained(a.out); tok.save_pretrained(a.out)
    json.dump({"base": a.model, "r": a.r, "alpha": a.alpha, "epochs": a.epochs, "max_train": a.max_train,
               "base_fact_recall": base_recall, "lora_fact_recall": recall},
              open(os.path.join(a.out, "metrics.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("saved ->", a.out, flush=True)


if __name__ == "__main__":
    main()