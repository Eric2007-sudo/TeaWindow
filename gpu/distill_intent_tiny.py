"""GPU：把 91.9% 的意图 BERT（teacher）蒸馏成可部署的小模型（student），并导出 int8 ONNX。
- 学生：默认 ckiplab/bert-tiny-chinese（~4 层，体积小，可上免费层）。
- 训练：硬标签 CE（有标注）+ 教师软标签 KD（含干净增广问句）。
用法：
  CUDA_VISIBLE_DEVICES=1 ~/teacloud/envs/qa/bin/python distill_intent_tiny.py \
    --teacher ~/teacloud/models/qa_intent_bert2 --student ckiplab/bert-tiny-chinese \
    --out ~/teacloud/models/qa_intent_tiny
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def encode_batch(tok, texts, dev, ml=32, bs=256):
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), bs):
            e = tok(texts[i:i + bs], truncation=True, max_length=ml, padding=True, return_tensors="pt")
            out.append({k: v.to(dev) for k, v in e.items()})
    return out


def teacher_logits(model, tok, texts, dev, ml=32, bs=256):
    logits = []
    model.eval()
    with torch.no_grad():
        for e in encode_batch(tok, texts, dev, ml, bs):
            logits.append(model(**e).logits.float().cpu())
    return torch.cat(logits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", default=os.path.expanduser("~/teacloud/models/qa_intent_bert2"))
    ap.add_argument("--student", default="ckiplab/bert-tiny-chinese")
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_intent_tiny"))
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--T", type=float, default=4.0)       # KD 温度
    ap.add_argument("--alpha", type=float, default=0.5)   # KD 权重
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    tok = AutoTokenizer.from_pretrained(a.teacher)
    teacher = AutoModelForSequenceClassification.from_pretrained(a.teacher).eval().to(dev)
    classes = json.load(open(os.path.join(a.teacher, "labels.json"), encoding="utf-8"))["classes"]
    cidx = {c: i for i, c in enumerate(classes)}

    tr = load(os.path.join(a.data, "intents_train.jsonl"))
    ev = load(os.path.join(a.data, "intents_eval.jsonl"))
    ch = load(os.path.join(a.data, "intents_challenge.jsonl"))
    unl = load(os.path.join(a.data, "pseudo_clean.jsonl"))
    tr_texts = [r["text"] for r in tr]
    tr_y = torch.tensor([cidx[r["intent"]] for r in tr])
    unl_texts = [r["text"] for r in unl]
    ev_texts = [r["text"] for r in ev]
    ev_y = np.array([r["intent"] for r in ev])
    print(f"classes={len(classes)} labeled={len(tr_texts)} unlabeled={len(unl_texts)} eval={len(ev)}", flush=True)

    # 教师软标签（预先算好）
    t_log_tr = teacher_logits(teacher, tok, tr_texts, dev)
    t_log_un = teacher_logits(teacher, tok, unl_texts, dev)
    t_acc = float((np.array([classes[i] for i in t_log_tr.argmax(-1).numpy()]) == np.array([r["intent"] for r in tr])).mean())
    eval_t = teacher_logits(teacher, tok, ev_texts, dev)
    print("teacher train-fit acc=%.4f  teacher eval acc=%.4f" % (t_acc, float((np.array([classes[i] for i in eval_t.argmax(-1).numpy()]) == ev_y).mean())), flush=True)

    student = AutoModelForSequenceClassification.from_pretrained(a.student, num_labels=len(classes)).to(dev)
    opt = torch.optim.AdamW(student.parameters(), lr=a.lr, weight_decay=0.01)
    ce = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
    n = len(tr_texts); idx = np.arange(n)

    def student_acc(rows):
        student.eval(); preds = []
        with torch.no_grad():
            for e in encode_batch(tok, [r["text"] for r in rows], dev):
                preds += list(student(**e).logits.argmax(-1).cpu().numpy())
        student.train()
        return float((np.array([classes[i] for i in preds]) == np.array([r["intent"] for r in rows])).mean())

    best_acc = -1.0; best_state = None; best_ep = 0; bad = 0
    student.train()
    for ep in range(a.epochs):
        np.random.shuffle(idx)
        tot = 0.0; nb = 0
        for b in range(0, n, a.bs):
            sel = idx[b:b + a.bs]
            e = tok([tr_texts[i] for i in sel], truncation=True, max_length=32, padding=True, return_tensors="pt")
            e = {k: v.to(dev) for k, v in e.items()}
            y = tr_y[sel].to(dev)
            logits = student(**e).logits
            loss = ce(logits, y)
            # 混合：同一批也加教师软标签 KD
            tl = t_log_tr[sel].to(dev)
            loss = (1 - a.alpha) * loss + a.alpha * F.kl_div(
                F.log_softmax(logits / a.T, dim=-1), F.softmax(tl / a.T, dim=-1), reduction="batchmean") * (a.T ** 2)
            opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss); nb += 1
        # 未标注 KD 一轮（干净增广问句）
        if unl_texts:
            m = len(unl_texts); ui = np.arange(m); np.random.shuffle(ui)
            for b in range(0, m, a.bs):
                sel = ui[b:b + a.bs]
                e = tok([unl_texts[i] for i in sel], truncation=True, max_length=32, padding=True, return_tensors="pt")
                e = {k: v.to(dev) for k, v in e.items()}
                tl = t_log_un[sel].to(dev)
                logits = student(**e).logits
                loss = F.kl_div(F.log_softmax(logits / a.T, dim=-1), F.softmax(tl / a.T, dim=-1), reduction="batchmean") * (a.T ** 2)
                opt.zero_grad(); loss.backward(); opt.step(); tot += float(loss); nb += 1
        ev_acc = student_acc(ev)
        ch_acc_ep = student_acc(ch) if ch else float("nan")
        print(f"epoch {ep+1}/{a.epochs} loss {tot/max(1,nb):.4f} eval_acc {ev_acc:.4f} challenge_acc {ch_acc_ep:.4f}", flush=True)
        if ev_acc > best_acc + 1e-6:
            best_acc, best_ep, bad = ev_acc, ep + 1, 0
            import copy as _copy
            best_state = _copy.deepcopy(student.state_dict())
        else:
            bad += 1
            if bad >= 3:
                print(f"early stop at epoch {ep+1} (best {best_ep} eval {best_acc:.4f})", flush=True)
                break
    if best_state is not None:
        student.load_state_dict(best_state)

    # 评测学生（eval + 挑战集）
    acc = student_acc(ev)
    ch_acc = student_acc(ch) if ch else float("nan")
    student.eval()
    print(f"STUDENT_EVAL_ACC={acc:.4f} STUDENT_CHALLENGE_ACC={ch_acc:.4f} (best_epoch={best_ep})", flush=True)

    os.makedirs(a.out, exist_ok=True)
    student.save_pretrained(a.out); tok.save_pretrained(a.out)
    json.dump({"classes": classes, "eval_acc": acc, "challenge_acc": ch_acc, "student": a.student, "teacher": a.teacher,
               "n_labeled": len(tr_texts), "n_unlabeled": len(unl_texts), "n_eval": len(ev), "n_challenge": len(ch),
               "T": a.T, "alpha": a.alpha},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)

    # 导出 int8 ONNX
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        student.cpu().eval()
        dummy = tok("今天有风险吗", return_tensors="pt")
        args = (dummy["input_ids"], dummy["attention_mask"], dummy.get("token_type_ids", torch.zeros_like(dummy["input_ids"])))
        onnx_path = os.path.join(a.out, "model.onnx")
        kw = dict(input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["logits"],
                  dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                                "token_type_ids": {0: "b", 1: "s"}, "logits": {0: "b"}}, opset_version=17)
        try:
            torch.onnx.export(student, args, onnx_path, dynamo=False, **kw)
        except TypeError:
            torch.onnx.export(student, args, onnx_path, **kw)
        qpath = os.path.join(a.out, "model.int8.onnx")
        quantize_dynamic(onnx_path, qpath, weight_type=QuantType.QInt8)
        fp = os.path.getsize(onnx_path) // 1024 // 1024
        q = os.path.getsize(qpath) // 1024 // 1024
        print(f"onnx fp32 {fp}MB int8 {q}MB", flush=True)
    except Exception as e:  # noqa: BLE001
        print("onnx skip:", e)
    print("saved ->", a.out)


if __name__ == "__main__":
    main()