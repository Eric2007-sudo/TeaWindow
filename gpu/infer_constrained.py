"""
M3+ 事实约束解码：生成多候选 → 用"校验器"对照事实打分 → 取最优；不达标则回退规则答案。
用法：~/teacloud/envs/qa/bin/python infer_constrained.py --model ~/teacloud/models/qa_d2t_15b
"""
import argparse
import json
import os
import re

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

SYS = ("你是梅坞采候 TeaWindow 的茶农助手。只依据给定事实作答，先给结论，再给1–2条可执行动作，"
       "简洁口语化（≤120字），涉及数值必须原样使用事实中的数字，不确定就说不确定，禁止编造。")
CASES = [
    ("要不要防冻", {"H": 7, "minTmin": 13.7, "minTmin_date": "2026-10-13", "frost_prob": 0.0}),
    ("要不要防冻", {"H": 30, "minTmin": 7.5, "minTmin_date": "2026-10-26", "frost_prob": 0.0, "clim_frost_prob": 0.09}),
    ("先采哪块地", {"first": ["云栖方向", "高处茶园"], "date": "2026-10-12"}),
    ("保险多少钱一亩", {"frost_th": 134, "pay": 1600, "fire": 7, "n": 12, "fair": 1000}),
    ("今年什么时候开采", {"pred": "2026-03-16", "mae": 1.8}),
    ("预计损失多少", {"value": 16000, "loss": 3200, "prem": 10, "benefit": 640}),
]


def expected_numbers(facts):
    out = []
    for v in facts.values():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(str(v))
        elif isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
            out.append(v)
        elif isinstance(v, list):
            out += [str(x) for x in v]
    return out


def verify(facts, text):
    score = tot = 0
    for n in expected_numbers(facts):
        tot += 1; score += 1 if (n in text) else 0
    if "minTmin" in facts:
        need = facts["minTmin"] <= 2 or (facts.get("H", 0) > 16 and facts.get("clim_frost_prob", 0) > 0.3)
        tot += 2
        bad = any(k in text for k in ["要防冻", "需防冻", "建议防冻", "提前防冻", "越冬", "覆盖", "熏烟"])
        if not need:
            score += 2 if not bad else 0
        else:
            score += 2 if any(k in text for k in ["防冻", "覆盖", "熏烟", "抢采"]) else 0
    tot += 1; score += 1 if len(text) <= 160 else 0
    return score / max(1, tot)


def fallback(q, f):
    if "minTmin" in f:
        tmin, d = f["minTmin"], f.get("minTmin_date", "")
        if tmin <= 2:
            return f"要防冻：{d} 前后最低 {tmin}℃，夜晨覆盖/熏烟并优先抢采。"
        return f"不用防冻：预报期最低 {tmin}℃（{d}），无霜冻风险。"
    if "first" in f:
        return f"建议先采：{'、'.join(f['first'])}（{f['date']}）。"
    if "fair" in f:
        return f"指数保险：阈值 {f['frost_th']} 度日、赔付 {f['pay']} 元/亩；历史赔付 {f['fire']}/{f['n']} 年，公平保费≈{f['fair']} 元/亩。"
    if "pred" in f:
        return f"今年开采日预测约 {f['pred']}（对官方开采日 MAE≈{f['mae']} 天）。"
    if "loss" in f:
        return f"亩产值约 {f['value']} 元，期望损失≈{f['loss']} 元/亩·年，工具减损≈{f['benefit']} 元/亩·年。"
    return "抱歉，我只能依据本项目数据作答。"


def gen_candidates(model, tok, q, f, dev, k=8):
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": f"问题：{q}\n事实：{json.dumps(f, ensure_ascii=False)}"}]
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    enc = tok(prompt, return_tensors="pt").to(dev)
    outs = model.generate(**enc, max_new_tokens=140, do_sample=True, temperature=0.9, top_p=0.95, num_return_sequences=k)
    res = []
    for o in outs:
        res.append(tok.decode(o[enc["input_ids"].shape[1]:], skip_special_tokens=True).strip())
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.expanduser("~/teacloud/models/qa_d2t_15b"))
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    cfg = os.path.join(a.model, "tokenizer_config.json")
    if os.path.exists(cfg):
        c = json.load(open(cfg, encoding="utf-8"))
        if isinstance(c.get("extra_special_tokens"), list):
            c["extra_special_tokens"] = {}
            json.dump(c, open(cfg, "w", encoding="utf-8"), ensure_ascii=False)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.float32).to(dev).eval()

    for q, f in CASES:
        cands = gen_candidates(model, tok, q, f, dev)
        scored = sorted(((verify(f, c), c) for c in cands), key=lambda x: -x[0])
        best_s, best = scored[0]
        used = "生成"
        if best_s < 0.75:
            best, used = fallback(q, f), "回退规则"
        print(f"Q: {q}\nFACTS: {json.dumps(f, ensure_ascii=False)}\n[{used} score={best_s:.2f}] {best}\n", flush=True)


if __name__ == "__main__":
    main()
