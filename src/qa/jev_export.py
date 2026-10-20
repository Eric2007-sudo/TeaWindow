"""导出待审问答为「主张 + 证据」审计包，供 TypeSafe Jev 或人工复核。

为什么是导出而不是在线调用：
  jev 是 Agent 侧工具（无公网 API / 无运行时凭据），不能作为线上服务的依赖。
  所以线上只负责把「答案、来源链、当天数据快照」留在库里（见 serve._log_qa），
  审计在离线执行：

      python src/qa/jev_export.py --limit 50
      # 生成 report/qa_jev_audit_input.json + report/qa_jev_audit_input.md

  然后在 Agent 里对每个 item 调用：
      jev_verify(claims=[答案中的关键句], evidence=[item.evidence], purpose=...)

用法：
  python src/qa/jev_export.py                 # 默认 50 条待审
  python src/qa/jev_export.py --limit 200 --all   # 含已审
"""
import argparse
import json
import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

import store  # noqa: E402


def _items(limit=50, include_reviewed=False):
    if include_reviewed:
        with store._LOCK:  # noqa: SLF001
            rows = store._db().execute(  # noqa: SLF001
                "SELECT id,ts,anon,lang,question,intent,answer,engine,chain,evidence "
                "FROM qa_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        keys = ("id", "ts", "anon", "lang", "question", "intent", "answer", "engine", "chain", "evidence")
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            try:
                d["chain"] = json.loads(d["chain"]) if d.get("chain") else []
            except Exception:  # noqa: BLE001
                d["chain"] = []
            out.append(d)
        return out
    return store.qa_log_pending(limit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--all", action="store_true", help="包含已审记录")
    ap.add_argument("--out", default=os.path.join(ROOT, "report", "qa_jev_audit_input.json"))
    ap.add_argument("--md", default=os.path.join(ROOT, "report", "qa_jev_audit_input.md"))
    ap.add_argument("--no-evidence", action="store_true", help="跳过没有证据快照的记录")
    a = ap.parse_args()

    items = _items(max(1, a.limit), a.all)
    if a.no_evidence:
        items = [x for x in items if (x.get("evidence") or "").strip()]

    bundle = {"generated_at": None, "count": len(items), "items": items}
    try:
        import datetime
        bundle["generated_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        pass

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

    lines = ["# 问答审计包（jev_verify 输入）", "",
             "共 %d 条。每条：问题 → 答案 → 来源链 → 当天数据证据。" % len(items), ""]
    for x in items:
        lines += ["## #%s · %s" % (x.get("id"), x.get("intent")),
                  "", "**问**：" + str(x.get("question") or ""),
                  "", "**答**：" + str(x.get("answer") or ""), ""]
        if x.get("chain"):
            lines += ["**来源链**：" + " → ".join(x["chain"]), ""]
        ev = (x.get("evidence") or "").strip()
        lines += ["**证据**：", "```", ev or "（无：该答案未包含可定位到数据行的日期）", "```", ""]
    with open(a.md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("[jev_export] items=%d -> %s" % (len(items), a.out))
    print("[jev_export] markdown -> %s" % a.md)
    print("[jev_export] 下一步：在 Agent 里 jev_verify(claims=..., evidence=[item.evidence])")


if __name__ == "__main__":
    main()
