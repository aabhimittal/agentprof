"""Reader for captured OpenAI-compatible traffic.

One JSON object per line, each holding the request that was sent and the
response that came back:

    {"request": {...}, "response": {...}, "t0": 1758240000.0, "t1": 1758240002.4}

`t0`/`t1` are optional epoch seconds. Aliases accepted for the two halves:
request/req/body/input and response/res/resp/output. This is what a LiteLLM
callback, an httpx event hook or a two-line logging wrapper produces, so no
framework-specific reader is needed.
"""
import json

from .. import fmt_openai
from ..model import llm_event, tool_event

_REQ = ("request", "req", "body", "input")
_RES = ("response", "res", "resp", "output", "completion")


def _pick(obj, names):
    for n in names:
        if isinstance(obj.get(n), dict):
            return obj[n]
    return None


def sniff(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                return None
            req, res = _pick(obj, _REQ), _pick(obj, _RES)
            if req and res and (req.get("messages") is not None or res.get("choices") is not None):
                return "openai"
            return None
    return None


def read(path):
    events, state = [], fmt_openai.new_state()
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            req, res = _pick(obj, _REQ), _pick(obj, _RES)
            if not req or not res:
                continue
            n += 1
            eid = "call-%d" % n
            blocks, pending = fmt_openai.blocks(req, state)
            t0 = obj.get("t0") or obj.get("start") or 0.0
            t1 = obj.get("t1") or obj.get("end") or t0
            for tid, name, label in pending:
                events.append(tool_event(tid, state.get("last_llm"), t0, t0, name, label, 0))
            events.append(llm_event(eid, None, t0, t1,
                                    res.get("model") or req.get("model"),
                                    fmt_openai.usage(res), blocks, "call %d" % n))
            state["last_llm"] = eid
    return events
