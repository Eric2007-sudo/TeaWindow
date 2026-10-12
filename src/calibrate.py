"""
概率校准与不确定性：
- 对 GBDT 复合风险概率做 Platt 校准（numpy 手写）；
- 报告 Brier 分数、可靠性曲线、AUC 的 bootstrap 95% 置信区间；
输出 models/calibration.json 与 report/figures/fig_calibration.png
"""
import json
import os
import sys

import numpy as np
import pandas as pd

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from model import build_features, rubric, GBDT  # noqa: E402

ROOT = os.path.dirname(SRC)
PROC = os.path.join(ROOT, "data", "processed")
MODELS = os.path.join(ROOT, "models")
FIGS = os.path.join(ROOT, "report", "figures")


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def fit_platt(scores, y, iters=3000, lr=0.1):
    x = logit(scores)
    a, b = 1.0, 0.0
    n = len(x)
    for _ in range(iters):
        p = sigmoid(a * x + b)
        ga = np.mean((p - y) * x)
        gb = np.mean(p - y)
        a -= lr * ga
        b -= lr * gb
    return a, b


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def roc_auc(y, p):
    order = np.argsort(p)
    y = np.asarray(y)[order]
    ranks = np.arange(1, len(y) + 1)
    npos, nneg = y.sum(), (1 - y).sum()
    if npos == 0 or nneg == 0:
        return float("nan")
    return (ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg)


def bootstrap_auc(y, p, n=1000, seed=42):
    rng = np.random.default_rng(seed)
    vals = []
    idx = np.arange(len(y))
    for _ in range(n):
        s = rng.choice(idx, size=len(idx), replace=True)
        if y[s].sum() in (0, len(s)):
            continue
        vals.append(roc_auc(y[s], p[s]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    df = pd.read_csv(os.path.join(PROC, "daily.csv"))
    X = build_features(df).values.astype(float)
    y, _ = rubric(df)
    y = np.asarray(y).astype(float)
    train = (df["year"] <= 2023).values
    test = (df["year"] > 2023).values

    m = GBDT().fit(X[train], y[train])
    s = m.predict_proba(X[test])
    yt = y[test].astype(int)

    a, b = fit_platt(s, yt)
    s_cal = sigmoid(a * logit(s) + b)

    # 可靠性曲线（10 分箱）
    bins = np.linspace(0, 1, 11)
    rel = []
    for i in range(10):
        msk = (s_cal >= bins[i]) & (s_cal < bins[i + 1] if i < 9 else s_cal <= 1.0)
        if msk.sum() > 0:
            rel.append({"bin": round((bins[i] + bins[i + 1]) / 2, 2),
                        "n": int(msk.sum()),
                        "pred": round(float(s_cal[msk].mean()), 3),
                        "obs": round(float(yt[msk].mean()), 3)})

    lo, hi = bootstrap_auc(yt, s)
    out = {
        "platt": {"a": round(float(a), 4), "b": round(float(b), 4)},
        "brier_raw": round(brier(s, yt), 4),
        "brier_calibrated": round(brier(s_cal, yt), 4),
        "auc": round(roc_auc(yt, s), 4),
        "auc_ci95": [round(lo, 4), round(hi, 4)],
        "reliability": rel,
        "n_test": int(test.sum()),
        "note": "Platt 校准 + bootstrap 置信区间；标签为弱标签(专家规则)。",
    }
    with open(os.path.join(MODELS, "calibration.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 图
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        os.makedirs(FIGS, exist_ok=True)
        fig, ax = plt.subplots(figsize=(5, 5))
        ax.plot([0, 1], [0, 1], "--", color="#8aa0b2", label="理想")
        ax.plot([r["pred"] for r in rel], [r["obs"] for r in rel], "o-", color="#4aa8ff", label="校准后")
        ax.set_xlabel("预测风险概率"); ax.set_ylabel("实际发生率")
        ax.set_title(f"可靠性曲线 (AUC={out['auc']}, 95%CI {out['auc_ci95']})")
        ax.legend(fontsize=8); fig.tight_layout()
        fig.savefig(os.path.join(FIGS, "fig_calibration.png"), dpi=130); plt.close(fig)
    except Exception as e:  # noqa: BLE001
        print("绘图跳过:", e)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("-> models/calibration.json")


if __name__ == "__main__":
    main()
