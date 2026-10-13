"""GPU：把微调后的 BGE 嵌入导出为 ONNX（含 mean-pooling+L2 归一化）并做 int8 量化，验证检索一致。
用法：CUDA_VISIBLE_DEVICES=1 ~/teacloud/envs/qa/bin/python export_embedder_onnx.py \
  --model ~/teacloud/models/qa_embedder --out ~/teacloud/models/qa_embedder_onnx
"""
import argparse
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402


class Pooled(nn.Module):
    def __init__(self, base):
        super().__init__()
        self.base = base

    def forward(self, input_ids, attention_mask, token_type_ids):
        h = self.base(input_ids=input_ids, attention_mask=attention_mask,
                      token_type_ids=token_type_ids).last_hidden_state
        m = attention_mask.unsqueeze(-1).float()
        z = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
        return F.normalize(z, dim=-1)


def pool_torch(base, tok, texts, dev, bs=64):
    base.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(texts), bs):
            e = tok(texts[i:i + bs], truncation=True, max_length=32, padding=True, return_tensors="pt").to(dev)
            h = base(**e).last_hidden_state
            m = e["attention_mask"].unsqueeze(-1).float()
            z = (h * m).sum(1) / m.sum(1).clamp(min=1e-9)
            out.append(F.normalize(z, dim=-1).cpu())
    return torch.cat(out)


def pool_onnx(path, tok, texts):
    s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    names = [i.name for i in s.get_inputs()]
    out = []
    for i in range(0, len(texts), 64):
        e = tok(texts[i:i + 64], truncation=True, max_length=32, padding=True)
        feed = {"input_ids": np.array(e["input_ids"], dtype=np.int64),
                "attention_mask": np.array(e["attention_mask"], dtype=np.int64)}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array(e.get("token_type_ids", [[0] * len(x) for x in e["input_ids"]]), dtype=np.int64)
        out.append(s.run(None, feed)[0])
    return np.concatenate(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_embedder"))
    ap.add_argument("--out", default=os.path.expanduser("~/teacloud/models/qa_embedder_onnx"))
    ap.add_argument("--data", default=os.path.expanduser("~/teacloud/data"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.model)
    base = AutoModel.from_pretrained(a.model).eval().cpu()
    net = Pooled(base).eval()
    dummy = tok("今天有风险吗", return_tensors="pt")
    args = (dummy["input_ids"], dummy["attention_mask"], dummy.get("token_type_ids", torch.zeros_like(dummy["input_ids"])))
    onnx_path = os.path.join(a.out, "model.onnx")
    kw = dict(input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["emb"],
              dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                            "token_type_ids": {0: "b", 1: "s"}, "emb": {0: "b"}}, opset_version=17)
    try:
        torch.onnx.export(net, args, onnx_path, dynamo=False, **kw)
    except TypeError:
        torch.onnx.export(net, args, onnx_path, **kw)
    tok.save_pretrained(a.out)
    print("exported", onnx_path, os.path.getsize(onnx_path) // 1024 // 1024, "MB", flush=True)

    from onnxruntime.quantization import QuantType, quantize_dynamic
    qpath = os.path.join(a.out, "model.int8.onnx")
    quantize_dynamic(onnx_path, qpath, weight_type=QuantType.QInt8)
    print("int8", qpath, os.path.getsize(qpath) // 1024 // 1024, "MB", flush=True)

    idx = [json.loads(l) for l in open(os.path.join(a.data, "intents_index.jsonl"), encoding="utf-8") if l.strip()]
    ev = [json.loads(l) for l in open(os.path.join(a.data, "intents_eval.jsonl"), encoding="utf-8") if l.strip()]
    ev_texts = {r["text"] for r in ev}
    idx = [r for r in idx if r["text"] not in ev_texts]     # 公平：索引中剔除评测原文
    itexts = [r["text"] for r in idx]
    ilab = np.array([r["intent"] for r in idx])
    etexts = [r["text"] for r in ev]
    eT = np.array([r["intent"] for r in ev])

    def report(name, Zidx, Zev):
        sim = Zev @ Zidx.T
        pred = ilab[sim.argmax(1)]
        acc = float((pred == eT).mean())
        print(f"{name} retrieval_acc={acc:.4f}", flush=True)
        return acc

    Zidx_t = pool_torch(base, tok, itexts, "cpu").numpy()
    Zev_t = pool_torch(base, tok, etexts, "cpu").numpy()
    report("torch", Zidx_t, Zev_t)
    for f in ("model.onnx", "model.int8.onnx"):
        Zidx = pool_onnx(os.path.join(a.out, f), tok, itexts)
        Zev = pool_onnx(os.path.join(a.out, f), tok, etexts)
        # 归一化（int8 可能略偏）
        Zidx = Zidx / (np.linalg.norm(Zidx, axis=1, keepdims=True) + 1e-9)
        Zev = Zev / (np.linalg.norm(Zev, axis=1, keepdims=True) + 1e-9)
        report(f, Zidx, Zev)
    json.dump({"classes": sorted(set(ilab.tolist())), "n_index": len(idx), "n_eval": len(ev)},
              open(os.path.join(a.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("DONE")


if __name__ == "__main__":
    main()