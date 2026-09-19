"""Normalized event model shared by every ingester.

An ingester turns a provider-specific log into an ordered list of Event dicts.
Two event kinds exist:

  llm   - one request to a model. Carries usage + the ordered list of context
          blocks that made up its input.
  tool  - one tool invocation requested by an llm event. Carries the byte size
          of the result it injected into the conversation.

Blocks are the unit of waste attribution: {h, bytes, kind, label, origin}.
'origin' is the id of the event that first put that block into the context, so
cost re-billed on later calls can be charged back to whoever created it.
"""
import hashlib

TOKENS_PER_BYTE = 0.25  # ~4 bytes/token for English + code. Estimate, not a tokenizer.


def fingerprint(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]


def block(text, kind, label, origin):
    return {
        "h": fingerprint(text),
        "bytes": len(text.encode("utf-8", "replace")),
        "kind": kind,
        "label": label[:120],
        "origin": origin,
    }


def llm_event(eid, parent, t0, t1, model, usage, blocks, label=None):
    return {
        "kind": "llm",
        "id": eid,
        "parent": parent,
        "t0": t0,
        "t1": t1,
        "model": model or "unknown",
        "usage": {
            "input": usage.get("input", 0),
            "output": usage.get("output", 0),
            "cache_read": usage.get("cache_read", 0),
            "cache_write": usage.get("cache_write", 0),
        },
        "blocks": blocks,
        "label": label or "assistant turn",
    }


def tool_event(eid, parent, t0, t1, name, label, result_bytes):
    return {
        "kind": "tool",
        "id": eid,
        "parent": parent,
        "t0": t0,
        "t1": t1,
        "name": name,
        "label": label,
        "result_bytes": result_bytes,
    }


def text_of(content):
    """Flatten an Anthropic-style content field to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for b in content:
        if isinstance(b, str):
            out.append(b)
            continue
        t = b.get("type")
        if t == "text":
            out.append(b.get("text", ""))
        elif t == "thinking":
            out.append(b.get("thinking", ""))
        elif t == "tool_use":
            out.append(b.get("name", "") + " " + _dumps(b.get("input")))
        elif t == "tool_result":
            out.append(text_of(b.get("content")))
        elif t in ("image", "document"):
            src = b.get("source", {}) or {}
            out.append(src.get("data", "")[:0] or "[%s %d bytes]" % (t, len(str(src.get("data", "")))))
        else:
            out.append(_dumps(b))
    return "\n".join(out)


def _dumps(obj):
    import json

    try:
        return json.dumps(obj, sort_keys=True)
    except Exception:
        return str(obj)
