"""GPU 端生成演示：加载微调后的 qa_d2t，对若干"问题+事实"生成自然回答。
用法：cd ~/teacloud && HF_ENDPOINT=https://hf-mirror.com ~/teacloud/envs/qa/bin/python infer_d2t.py
"""
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

SRC = os.path.expanduser("~/teacloud/models/qa_d2t")
SYS = ("你是梅坞采候 TeaWindow 的茶农助手。只依据给定事实作答，先给结论，再给1–2条可执行动作，"
       "简洁口语化（≤120字），涉及数值要用事实里的数字，不编造。")

CASES = [
    ("要不要防冻", '{"H": 30, "minTmin": 7.5, "minTmin_date": "2026-10-26", "frost_prob": 0.0, "clim_frost_prob": 0.09}'),
    ("先采哪块地", '{"first": ["云栖方向", "高处茶园"], "date": "2026-10-12"}'),
    ("保险多少钱一亩", '{"frost_th": 134, "pay": 1600, "fire": 7, "n": 12, "fair": 1000}'),
    ("今年什么时候开采", '{"pred": "2026-03-16", "mae": 1.8}'),
    ("预计损失多少", '{"value": 16000, "loss": 3200, "prem": 10, "benefit": 640}'),
]


def main():
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(SRC)
    model = AutoModelForCausalLM.from_pretrained(SRC, dtype=torch.float32).to(dev).eval()
    out = []
    for q, facts in CASES:
        msgs = [{"role": "system", "content": SYS},
                {"role": "user", "content": f"问题：{q}\n事实：{facts}"}]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt").to(dev)
        ids = model.generate(**enc, max_new_tokens=160, do_sample=False)
        gen = tok.decode(ids[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
        out.append(f"Q: {q}\nFACTS: {facts}\nA: {gen}\n")
    text = "\n".join(out)
    open(os.path.expanduser("~/teacloud/out/d2t_samples.txt"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
