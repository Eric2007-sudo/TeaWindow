"""
问答闭环采集：把匿名问答日志 → 项目相关性筛选 → DeepSeek 教师纠偏 → 生成回训数据/审阅清单。

- 只保留**项目相关**问题；不保留 IP/身份（日志本就匿名）。
- 教师仅用于：①给问题打我们类目下的意图标签（回训意图模型）；②给出"理想答法"用于对照纠偏规则。
- **不直接抄教师文本**：教师答案只进审阅清单（report/qa_review.md），由人修正规则/模板后再回训。

用法：
  python src/qa/harvest.py --limit 50                 # 本地库（store）
  python src/qa/harvest.py --use-api --limit 50       # 线上（读取 .env 的 RENDER/ADMIN）
  python src/qa/harvest.py --dry                      # 不写库、不调用教师（仅打印筛选结果）
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
REPORT = os.path.join(ROOT, "report")
sys.path.insert(0, os.path.join(ROOT, "src"))

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
CLASSES = ["data_source", "decision", "drought", "frost", "greet", "harvest_date", "heat", "insurance",
           "model", "oos", "ops", "pick_window", "plot", "rain", "risk_today", "schedule", "value"]
OFFTOPIC = ["药", "疼", "感冒", "股票", "基金", "彩票", "贷款", "汇率"]


def _key():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in io.open(p, encoding="utf-8", errors="ignore"):
            if line.strip().startswith("DEEPSEEK_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _chat(system, user, temperature=0.2):
    key = _key()
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    body = {"model": MODEL, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = requests.post(API_URL, json=body, timeout=120,
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _relevant(q, intent):
    if intent in ("oos", "greet", "memory", "cancel", "task_ref"):
        return False
    if any(w in q for w in OFFTOPIC):
        return False
    return 2 <= len(q) <= 120


def _teacher(q):
    """返回 {intent, reference, verdict, note}。"""
    sysmsg = ("你是农业气象与茶园管理专家，也是意图标注员。只处理梅家坞龙井茶园气候与采摘/养护相关问题。")
    user = (f"问题：{q}\n"
            f"可选意图（必须从中选择）：{', '.join(CLASSES)}\n"
            "请给出 JSON：{\"intent\":\"...\",\"reference\":\"60字内的理想回答（含关键结论与边界）\","
            "\"verdict\":\"ok|fix|reject\",\"note\":\"若 fix，指出规则/口径问题；若 reject，说明无关\"}")
    txt = _chat(sysmsg, user)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--use-api", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    if a.use_api:
        env = io.open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="ignore").read()
        tok = re.search(r"ADMIN_TOKEN\s*=\s*(\S+)", env)
        import urllib.request
        url = os.environ.get("TW_URL", "https://teawindow.onrender.com") + f"/api/qa/logs?limit={a.limit}"
        r = urllib.request.Request(url, headers={"X-Admin-Token": (tok.group(1) if tok else "")})
        data = json.loads(urllib.request.urlopen(r, timeout=60).read())
        logs = data.get("pending", [])
    else:
        import store
        logs = store.qa_log_pending(a.limit)

    print(f"待处理日志 {len(logs)} 条")
    kept, review = [], []
    for lg in logs:
        q, it = lg.get("question", ""), lg.get("intent", "")
        if not _relevant(q, it):
            continue
        if a.dry:
            kept.append({"text": q, "intent": it})
            continue
        t = _teacher(q)
        time.sleep(0.6)
        if not t:
            continue
        if t.get("verdict") == "reject" or t.get("intent") == "oos":
            continue
        kept.append({"text": q, "intent": t.get("intent", it)})
        review.append({"q": q, "ours": lg.get("answer", ""), "teacher": t.get("reference", ""),
                       "verdict": t.get("verdict"), "note": t.get("note", "")})
        if not a.use_api:
            import store
            try:
                store.qa_log_set(lg["id"], teacher=t.get("reference"), teacher_model=MODEL,
                                 relevant=1, reviewed=1)
            except Exception:  # noqa: BLE001
                pass

    os.makedirs(QA, exist_ok=True)
    with io.open(os.path.join(QA, "harvest_intents.jsonl"), "a", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    md = ["# 问答纠偏清单（教师对照，非抄袭）\n",
          f"> 来源：匿名问答日志；教师模型 `{MODEL}`；仅作对照与意图标注，最终答案仍由本项目规则/模型生成。\n"]
    for r in review:
        md.append(f"## {r['q']}\n- 类型：**{r['verdict']}** {('- ' + r['note']) if r['note'] else ''}\n"
                  f"- 我们：{r['ours'][:200]}\n- 参考：{r['teacher'][:200]}\n")
    if review:
        os.makedirs(REPORT, exist_ok=True)
        io.open(os.path.join(REPORT, "qa_review.md"), "w", encoding="utf-8").write("\n".join(md))
    print(f"保留 {len(kept)} 条（data/qa/harvest_intents.jsonl）；审阅 {len(review)} 条（report/qa_review.md）")


if __name__ == "__main__":
    main()