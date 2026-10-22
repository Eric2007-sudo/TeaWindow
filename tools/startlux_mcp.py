#!/usr/bin/env python3
"""StartLux-Decision MCP server (stdio) — 给 OpenCode 用的本地工具服务。

OpenCode 的 provider 只会说 OpenAI chat/completions，而 StartLux 是「类型化决策」API
(/v1/decisions)，两者协议不同。所以不要把 StartLux 配成 chat 模型，而是作为一个 MCP
工具暴露给 agent：agent 需要做分类/是判断/打分时显式调用。

用法（opencode.jsonc）：
  {
    "mcp": {
      "servers": {
        "startlux": {
          "type": "local",
          "command": ["python", "tools/startlux_mcp.py"],
          "environment": { "STARTLUX_API_KEY": "{env:STARTLUX_API_KEY}" }
        }
      }
    }
  }

工具：
  startlux_decide  — 传 state + questions（choice/noul/score），返回每个选项的概率
  startlux_choose  — 便捷版：state + options[] → 选一个，返回概率

依赖：requests（项目已依赖）。API key 只从环境变量读取。
"""
import json
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import decision_client  # noqa: E402

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "startlux_decide",
        "description": ("Ask StartLux-Decision (27B AutoThink) typed questions about a state. "
                        "questions: {id: {type: 'choice'|'noul'|'score', instructions, criteria}}. "
                        "Returns calibrated probabilities per option. Use it for classification, "
                        "yes/no checks and graded scores — not for writing prose."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": ["string", "object"], "description": "Text or JSON describing the situation"},
                "questions": {"type": "object", "description": "Map of question id → typed question"},
                "think_mode": {"type": "string", "enum": ["auto", "never", "always"], "default": "auto"},
                "gate": {"type": "number", "default": 0.9},
            },
            "required": ["state", "questions"],
        },
    },
    {
        "name": "startlux_choose",
        "description": ("Convenience wrapper: pick one of the given options for a state. "
                        "Returns the chosen option and its probability."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": ["string", "object"]},
                "instructions": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "think_mode": {"type": "string", "enum": ["auto", "never", "always"], "default": "auto"},
                "gate": {"type": "number", "default": 0.9},
            },
            "required": ["state", "instructions", "options"],
        },
    },
]


def _text(payload, is_error=False):
    if isinstance(payload, str):
        body = payload
    else:
        body = json.dumps(payload, ensure_ascii=False, indent=1)
    return {"content": [{"type": "text", "text": body}], "isError": bool(is_error)}


def _call(name, args):
    if not decision_client.enabled():
        return _text("STARTLUX_API_KEY is not set; export it before starting OpenCode.", True)

    if name == "startlux_decide":
        out = decision_client.decide(args["state"], args["questions"],
                                     think_mode=args.get("think_mode", "auto"),
                                     gate=args.get("gate", 0.9))
        return _text(out)

    if name == "startlux_choose":
        opts = args["options"]
        if not isinstance(opts, list) or len(opts) < 2:
            return _text("options must be an array with at least two entries", True)
        criteria = {str(o): str(o) for o in opts}
        questions = {"choice": {"type": "choice", "instructions": args["instructions"], "criteria": criteria}}
        out = decision_client.decide(args["state"], questions,
                                     think_mode=args.get("think_mode", "auto"),
                                     gate=args.get("gate", 0.9))
        label, conf, raw = decision_client.best(out.get("answers"), "choice")
        out["picked"] = label
        out["confidence"] = round(conf, 4)
        return _text(out)

    return _text("unknown tool: " + str(name), True)


def _handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "startlux-decision", "version": "1.0.0"},
            "instructions": ("StartLux-Decision returns calibrated probabilities for typed questions "
                             "(choice / noul / score). Use startlux_decide for structured judgement; "
                             "it does not write long text."),
        }}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = _call(name, args)
        except Exception as e:  # noqa: BLE001
            result = _text("StartLux error: " + repr(e)[:300], True)
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: " + str(method)}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        resp = _handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
