"""StartLux-Decision 客户端（可选依赖，未配置时完全降级）。

它不是聊天模型：输入是「状态 + 类型化问题」，输出是每个选项的校准概率
（choice / noul / score），不生成散文。适合做意图路由、动作交叉校验、人工复核分流。

配置（放 .env，不要提交）：
  STARTLUX_API_KEY=bk-...                 # 必填；也可用 BAMBOO_API_KEY
  STARTLUX_BASE_URL=https://api.bamboonode.dev/v1
  STARTLUX_MODEL=startlux-decision-27b-autothink
  STARTLUX_TIMEOUT=8

设计原则：
- 默认关闭：没有 key 时 enabled() = False，所有调用返回 None，业务继续用规则；
- 绝不覆盖安全结论：只作为「第二意见」，分歧时标记需要人工复核；
- 不记录 key，不把 key 写进日志或返回体。
"""
import os

import requests

DEFAULT_BASE = "https://api.bamboonode.dev/v1"
DEFAULT_MODEL = "startlux-decision-27b-autothink"


def _load_env():
    """独立脚本/测试里也能读到项目 .env（不覆盖已有环境变量）。"""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(root, ".env")
        if not os.path.exists(p):
            return
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except Exception:  # noqa: BLE001
        pass


_load_env()


def _base():
    return (os.environ.get("STARTLUX_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _key():
    return os.environ.get("STARTLUX_API_KEY") or os.environ.get("BAMBOO_API_KEY") or ""


def enabled():
    return bool(_key())


def model_id():
    return os.environ.get("STARTLUX_MODEL") or DEFAULT_MODEL


def decide(state, questions, think_mode="auto", gate=0.9, timeout=None):
    """调用 /v1/decisions，返回原始 JSON（含 answers / usage / model）。

    questions 形如：
      {"action": {"type": "choice", "instructions": "...", "criteria": {"采": "...", "防": "..."}},
       "urgent": {"type": "noul", "instructions": "..."},
       "severity": {"type": "score", "instructions": "...", "criteria": ["低", "中", "高"]}}
    """
    if not enabled():
        raise RuntimeError("STARTLUX_API_KEY not set")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty object")
    if len(questions) > 12:
        raise ValueError("too many questions (max 12)")
    if not isinstance(state, (str, dict)):
        raise ValueError("state must be a string or an object")

    payload = {
        "model": model_id(),
        "state": state,
        "questions": questions,
        "think_mode": think_mode if think_mode in ("auto", "never", "always") else "auto",
        "gate": float(gate),
    }
    t = float(timeout or os.environ.get("STARTLUX_TIMEOUT", "8"))
    r = requests.post(_base() + "/decisions", json=payload,
                      headers={"Authorization": "Bearer " + _key(),
                               "Content-Type": "application/json"},
                      timeout=t)
    if r.status_code >= 400:
        raise RuntimeError(f"startlux http {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not isinstance(data.get("answers"), dict):
        raise RuntimeError("startlux: response missing answers")
    return data


def try_decide(state, questions, **kw):
    """永不抛异常：失败/未配置返回 None，调用方继续用规则。"""
    try:
        return decide(state, questions, **kw)
    except Exception as e:  # noqa: BLE001
        try:
            print("[startlux] 跳过:", repr(e)[:160])
        except Exception:  # noqa: BLE001
            pass
        return None


def best(answers, qid):
    """把单题答案收敛成 (label, confidence, raw)。"""
    a = (answers or {}).get(qid) or {}
    t = a.get("type")
    if t == "choice":
        probs = a.get("probabilities") or {}
        if not probs:
            return None, 0.0, a
        k = max(probs, key=lambda x: probs[x])
        return k, float(probs[k]), a
    if t == "noul":
        p = float(a.get("noul") or 0.0)
        return ("yes" if p >= 0.5 else "no"), max(p, 1.0 - p), a
    if t == "score":
        return a.get("score"), float(a.get("confidence") or 0.0), a
    return None, 0.0, a
