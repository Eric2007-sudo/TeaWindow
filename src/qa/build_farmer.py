"""
用 DeepSeek 模拟真实茶农提问，构建意图训练/评测/挑战集与复合多维问题集。

- 真实性：口语、杭州方言用词、错别字、简称、情绪化、不完整句。
- 多维：一句话含 2–3 个诉求（复合任务），用于任务规划与一致性回归。
产出（data/qa/）：
  farmer_train.jsonl / farmer_eval.jsonl / farmer_challenge.jsonl   {"text","intent"}
  farmer_multi.jsonl                                                 {"text","intent","also":[...]}
用法：
  python src/qa/build_farmer.py --mode train --per 20 --rounds 2
  python src/qa/build_farmer.py --mode eval --per 6
  python src/qa/build_farmer.py --mode challenge --per 10
  python src/qa/build_farmer.py --mode multi --per 30
"""
import argparse
import io
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QA = os.path.join(ROOT, "data", "qa")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

INTENT_HINTS = {
    "risk_today": "今天/现在有没有风险、要不要当心、天气怎样、有没有预警",
    "frost": "霜冻、倒春寒、防冻、夜里低温、覆盖、熏烟、下霜",
    "heat": "高温、晒伤、灼伤、遮阳、热害、太阳大",
    "drought": "干旱、缺水、要不要浇水、灌溉、墒情、土干",
    "rain": "下雨、连阴雨、排水、涝、湿度大、摊青",
    "pick_window": "什么时候采、采摘时机、明前雨前、开采窗口、适不适合采",
    "schedule": "先采哪块地、采茶顺序、排班、人手怎么安排",
    "decision": "抢采还是等、冒险采、值不值得、等两天",
    "harvest_date": "今年什么时候开采、上市、几号开摘",
    "insurance": "保险、保费、理赔、赔付、保额、怎么赔、划算不划算",
    "value": "能省多少钱、损失多少、值多少、有没有用",
    "data_source": "数据哪来的、准不准、可不可信、靠谱吗、有没有传感器/台站/卫星",
    "model": "用什么模型、AI、准确率、误报漏报、怎么算出来的",
    "plot": "哪块地风险高、地块、坡地、海拔、地形、谷地",
    "ops": "多久更新、多久刷新、数据新不新、过期了吗、断网怎么办、提前期误差、运行批次",
    "greet": "打招呼、感谢、在吗、您好、辛苦了",
}
CLASSES = [c for c in INTENT_HINTS]


def _key():
    for line in io.open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="ignore"):
        if line.strip().startswith("DEEPSEEK_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _chat(system, user, temperature=1.0):
    key = _key()
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    body = {"model": MODEL, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = None
    for i in range(5):
        try:
            r = requests.post(API_URL, json=body, timeout=120,
                              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            if r.status_code == 429:
                time.sleep(8 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 + i * 4)
    raise RuntimeError(f"调用失败: {last}")


def _parse_list(text):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for x in arr:
        s = (x.get("text") if isinstance(x, dict) else x) or ""
        s = re.sub(r"\s+", " ", str(s)).strip()
        if 2 <= len(s) <= 60:
            out.append(s)
    return out


SYS = ("你是杭州西湖龙井核心产区（梅家坞）的资深茶农，说话口语化，偶尔带杭州方言用词和错别字，"
       "语气像在茶园里当面问技术员。你了解采茶、防霜冻、高温、干旱、连阴雨、灌溉、保险、开采期等。")


def gen_intent(intent, hint, n, style):
    user = (f"围绕【{hint}】，写出 {n} 个**互不相同**的茶农提问（每个一行，短句，口语化）。"
            f"{style}\n"
            "要求：只输出 JSON 数组，元素为字符串；不要编号、不要解释、不要重复。\n"
            '例如：["师傅，这两天要不要防霜啊","明前还能不能采了"]')
    return _parse_list(_chat(SYS, user))


def gen_multi(n):
    user = ("写出 %d 个**一句话里包含 2~3 个诉求**的茶农复合提问（真实口吻，可能有错别字）。" % n +
            "示例：'先说未来七天最大风险，再说最大降雨日，最后告诉我数据多久更新一次'；"
            "'哪块地最容易冻，要不要防冻，保险能赔多少'。\n"
            "只输出 JSON 数组，元素是字符串。")
    return _parse_list(_chat(SYS, user))


def _append(path, rows):
    with io.open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _exists(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["train", "eval", "challenge", "multi"])
    ap.add_argument("--per", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()
    os.makedirs(QA, exist_ok=True)

    if args.mode == "multi":
        path = os.path.join(QA, "farmer_multi.jsonl")
        total = 0
        for k in range(args.rounds):
            rows = gen_multi(args.per)
            seen = set()
            with io.open(path, "a", encoding="utf-8") as f:
                for s in rows:
                    if s in seen:
                        continue
                    seen.add(s)
                    f.write(json.dumps({"text": s, "intent": "compound", "also": []}, ensure_ascii=False) + "\n")
                    total += 1
            print(f"[multi] round {k+1}: +{len(rows)} (total {total})")
        return

    styles = {
        "train": "可以有错别字、简称、方言、口语碎片。",
        "eval": "句式与常见说法略微不同，测试泛化（不要和训练常用句雷同）。",
        "challenge": "尽量刁钻：长句、方言、错别字、省略主语、情绪化、与相邻主题易混。",
    }
    for intent, hint in INTENT_HINTS.items():
        path = os.path.join(QA, f"farmer_{args.mode}.jsonl")
        got = 0
        seen = set()
        for k in range(args.rounds):
            rows = gen_intent(intent, hint, args.per, styles[args.mode])
            new = [s for s in rows if s not in seen]
            seen.update(new)
            _append(path, [{"text": s, "intent": intent} for s in new])
            got += len(new)
        print(f"[{args.mode}] {intent}: +{got}")


if __name__ == "__main__":
    main()