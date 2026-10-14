"""
M5 多轮对话 SFT 数据：messages 格式（system + 多轮 user/assistant），
同一事实/目标日期贯穿多轮（含追问/改口/措施），用于 LoRA 微调小型 instruct 模型提升多轮体验。
输出 data/qa/mt/{train,eval}.jsonl
用法：python src\\qa\\build_multiturn.py
"""
import json
import os
import random
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SRC))
sys.path.insert(0, SRC)
import build_d2t as d2t  # noqa: E402

OUT = os.path.join(ROOT, "data", "qa", "mt")
rng = random.Random(2026)

SYS = d2t.SYS
FOLLOW_Q = ["那明天呢", "它的最低温是多少", "那一天要不要排水", "改成灌溉", "为什么会这样", "具体点",
            "那后天呢", "最高温呢", "降雨多少", "该采取什么措施", "要遮盖吗"]


def _one_turn(intent):
    fgen, agen = d2t.SPEC[intent]
    facts, need = fgen()
    q = rng.choice(d2t.qbank()[intent])
    ans = agen(facts, need)
    return facts, need, q, ans


def conv():
    it = rng.choice(list(d2t.SPEC.keys()))
    facts, need, q, ans = _one_turn(it)
    fact_json = json.dumps(facts, ensure_ascii=False)
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": f"问题：{q}\n事实：{fact_json}"},
            {"role": "assistant", "content": ans}]
    # 2–3 轮追问：同一 facts（同一天口径），体现"追问/指代/改口"
    n_more = 2 if rng.random() < 0.6 else 1
    for _ in range(n_more):
        q2 = rng.choice(FOLLOW_Q)
        a2 = d2t.SPEC[it][1](facts, need)
        msgs.append({"role": "user", "content": f"问题：{q2}\n事实：{fact_json}"})
        msgs.append({"role": "assistant", "content": a2})
    return {"messages": msgs}


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = [conv() for _ in range(4000)]
    rng.shuffle(rows)
    cut = int(len(rows) * 0.9)
    with open(os.path.join(OUT, "train.jsonl"), "w", encoding="utf-8") as f:
        for r in rows[:cut]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "eval.jsonl"), "w", encoding="utf-8") as f:
        for r in rows[cut:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"多轮对话样本: train={cut} eval={len(rows)-cut} -> data/qa/mt/")


if __name__ == "__main__":
    main()