"""
A-2 本机训练意图分类器：字符 n-gram 特征 + softmax 逻辑回归（纯 numpy）。
产出 models/qa_intent.json 与 report/qa_model.md（准确率/混淆矩阵/样例）。
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QA = os.path.join(ROOT, "data", "qa")
MODELS = os.path.join(ROOT, "models")
REPORT = os.path.join(ROOT, "report")


def grams(text):
    t = "".join(ch for ch in text if ch.strip())
    out = list(t) + [t[i:i + 2] for i in range(len(t) - 1)]
    return out


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_vocab(texts):
    from collections import Counter
    c = Counter()
    for t in texts:
        c.update(grams(t))
    vocab = {g: i for i, (g, n) in enumerate(c.items()) if n >= 1}
    return vocab


def vectorize(texts, vocab):
    D = len(vocab)
    X = np.zeros((len(texts), D), dtype="float32")
    for i, t in enumerate(texts):
        for g in grams(t):
            j = vocab.get(g)
            if j is not None:
                X[i, j] += 1.0
        s = X[i].sum()
        if s > 0:
            X[i] /= s
    return X


def softmax(Z):
    Z = Z - Z.max(axis=1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(axis=1, keepdims=True)


def train(X, y, C, iters=10000, lr=2.0, l2=1e-5):
    N, D = X.shape
    W = np.zeros((C, D), dtype="float32")
    b = np.zeros(C, dtype="float32")
    Y = np.zeros((N, C), dtype="float32"); Y[np.arange(N), y] = 1
    for it in range(iters):
        P = softmax(X @ W.T + b)
        G = (P - Y) / N
        W -= lr * (G.T @ X + l2 * W)
        b -= lr * G.sum(0)
        if it % 500 == 0:
            loss = -np.log(np.clip(P[np.arange(N), y], 1e-9, 1)).mean()
            print(f"  iter {it} loss {loss:.4f}")
    return W, b


def main():
    os.makedirs(MODELS, exist_ok=True); os.makedirs(REPORT, exist_ok=True)
    tr = load(os.path.join(QA, "intents_train.jsonl"))
    ev = load(os.path.join(QA, "intents_eval.jsonl"))
    # 若存在 GPU-BERT 蒸馏的伪标签（conf>=0.9），并入训练
    pl = os.path.join(QA, "pseudo_labeled.jsonl")
    if os.path.exists(pl):
        extra = sorted([r for r in load(pl) if r.get("conf", 0) >= 0.9], key=lambda r: -r["conf"])[:1500]
        tr = tr + [{"text": r["text"], "intent": r["intent"]} for r in extra]
        print(f"蒸馏伪标签样本并入: {len(extra)}")
    classes = sorted({r["intent"] for r in tr})
    cidx = {c: i for i, c in enumerate(classes)}
    vocab = build_vocab([r["text"] for r in tr])
    Xtr = vectorize([r["text"] for r in tr], vocab)
    ytr = np.array([cidx[r["intent"]] for r in tr])
    Xev = vectorize([r["text"] for r in ev], vocab)
    yev = np.array([cidx[r["intent"]] for r in ev])
    print(f"类别={len(classes)} 训练={len(tr)} 评测={len(ev)} 特征={Xtr.shape[1]}")
    iters = 4000 if len(tr) > 1200 else 10000
    W, b = train(Xtr, ytr, len(classes), iters=iters)

    def predict(X):
        return (X @ W.T + b).argmax(1)
    acc = float((predict(Xev) == yev).mean())
    # 混淆矩阵
    K = len(classes)
    cm = np.zeros((K, K), dtype=int)
    for t, p in zip(yev, predict(Xev)):
        cm[t, p] += 1
    md = ["# 自研问答意图分类器（本机 numpy）\n",
          f"- 类别 {len(classes)}；训练 {len(tr)}，评测 {len(ev)}；字符 1-2gram 特征 {Xtr.shape[1]} 维。",
          f"- **评测准确率 = {acc*100:.1f}%**\n",
          "## 各类分布（评测集）"]
    for c in classes:
        i = cidx[c]; total = int(cm[i].sum())
        md.append(f"- {c}: {total} 条")
    md += ["\n## 样例预测"]
    for r in ev[:12]:
        p = classes[predict(vectorize([r["text"]], vocab))[0]]
        md.append(f"- “{r['text']}” → {p}（真值 {r['intent']}）{'✓' if p==r['intent'] else '✗'}")
    open(os.path.join(REPORT, "qa_model.md"), "w", encoding="utf-8").write("\n".join(md))

    json.dump({"classes": classes, "vocab": vocab, "W": W.tolist(), "b": b.tolist(),
               "acc": acc, "n_train": len(tr), "n_eval": len(ev)},
              open(os.path.join(MODELS, "qa_intent.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"准确率={acc*100:.1f}% -> models/qa_intent.json, report/qa_model.md")


if __name__ == "__main__":
    main()
