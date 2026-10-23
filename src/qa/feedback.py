"""离线反馈：把问答日志聚成可执行的改进项（只读日志，不改线上）。

用法：
  python src/qa/feedback.py --limit 2000
  -> report/qa_feedback.md

原则：
- 不改模型权重，不改规则，只输出"该看哪一类失败"；
- 训练/校准标签必须来自外部真值（官方开采日、台站观测、田间记录），
  不把 StartLux 的判断当作标签——它只用于"这条答案是否被证据支持"的运行时校验。
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import store  # noqa: E402

DIM_LABEL = {
    "supported": "证据支持不足",
    "actionable": "缺少可执行动作",
    "safe": "边界/免责不足",
    "data": "数据体检未通过",
}
DIM_HINT = {
    "supported": "检查该 intent 的答案是否引用了证据快照里没有的字段（版本号、概率、上游 URL）。",
    "actionable": "该 intent 的模板需要补一个明确动作（采 / 防冻 / 灌溉 / 观察 / 排水）。",
    "safe": "检查是否出现绝对化承诺，补“决策辅助 + 官方预警优先”的固定句。",
    "data": "先修数据管线：新鲜度、日期空洞、上游漂移；再谈答案质量。",
}


def classify(row):
    """返回该条日志命中的失败维度列表。"""
    dims = []
    g = row.get("gate") or {}
    scores = g.get("scores") or {}
    try:
        if scores.get("supported") is not None and float(scores["supported"]) < 0.45:
            dims.append("supported")
        if scores.get("actionable") is not None and float(scores["actionable"]) < 0.35:
            dims.append("actionable")
        if scores.get("safe") is not None and float(scores["safe"]) < 0.35:
            dims.append("safe")
    except Exception:  # noqa: BLE001
        pass
    data = g.get("data") or {}
    if data.get("verdict") == "unreliable":
        dims.append("data")
    return dims


def build(rows):
    clusters = defaultdict(lambda: {"count": 0, "examples": []})
    gated = 0
    decisions = Counter()
    for r in rows:
        g = r.get("gate") or {}
        if not g:
            continue
        gated += 1
        decisions[str(g.get("decision"))] += 1
        for d in classify(r):
            key = (r.get("intent") or "unknown", d)
            c = clusters[key]
            c["count"] += 1
            if len(c["examples"]) < 3:
                c["examples"].append((r.get("question") or "")[:60])
    items = sorted(clusters.items(), key=lambda kv: -kv[1]["count"])
    return {"total": len(rows), "gated": gated, "decisions": dict(decisions),
            "clusters": [{"intent": k[0], "dim": k[1], **v} for k, v in items]}


def _baseline():
    out = {}
    try:
        m = json.load(open(os.path.join(ROOT, "models", "metrics.json"), encoding="utf-8"))
        out["ml"] = m.get("ml")
        out["test_years"] = m.get("test_years")
    except Exception:  # noqa: BLE001
        pass
    try:
        p = json.load(open(os.path.join(ROOT, "web", "phenology.json"), encoding="utf-8"))
        out["phenology"] = {"fixed": p.get("fixed", {}).get("mae"),
                            "forward": (p.get("forward") or {}).get("mae")}
    except Exception:  # noqa: BLE001
        pass
    return out


def render(res, base):
    lines = ["# 问答反馈报告（离线）", "",
             f"- 日志条数：{res['total']}（含 gate：{res['gated']}）",
             f"- 判定分布：{res['decisions'] or '—'}", ""]
    if not res["clusters"]:
        lines += ["暂无失败聚类：要么样本太少，要么护栏未开启。", ""]
    else:
        lines += ["## 失败聚类（按次数）", "",
                  "| 次数 | intent | 失败项 | 建议检查 |", "|---:|---|---|---|"]
        for c in res["clusters"][:20]:
            lines.append(f"| {c['count']} | {c['intent']} | {DIM_LABEL.get(c['dim'], c['dim'])} | {DIM_HINT.get(c['dim'], '')} |")
        lines += ["", "### 代表性问题"]
        for c in res["clusters"][:8]:
            lines.append(f"- **{c['intent']} / {DIM_LABEL.get(c['dim'])}**：" + "；".join(x for x in c["examples"] if x))
    lines += ["", "## 外部真值基线（回归用，不是模型自评）"]
    if base.get("ml"):
        lines.append(f"- 冻结评估集 {base.get('test_years')}：AUC {base['ml'].get('auc')} / F1 {base['ml'].get('f1')}")
    if base.get("phenology"):
        lines.append(f"- 官方开采日：不拟合 MAE {base['phenology'].get('fixed')} 天；前向 {base['phenology'].get('forward')} 天")
    lines += ["", "## 标签从哪来",
              "- 用官方开采日、台站观测、田间正/负样本做校准与回归；",
              "- **不把 StartLux 的判定当训练标签**：它只回答“这条答案是否被当前证据支持”，是运行时护栏，不是真值。",
              "- 每轮改动都在冻结评估集上回归，指标变差即回滚。", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--out", default=os.path.join(ROOT, "report", "qa_feedback.md"))
    a = ap.parse_args()
    rows = store.qa_log_all(max(1, a.limit))
    res = build(rows)
    md = render(res, _baseline())
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(md)
    print(f"[feedback] logs={res['total']} gated={res['gated']} clusters={len(res['clusters'])}")
    print("->", a.out)


if __name__ == "__main__":
    main()
