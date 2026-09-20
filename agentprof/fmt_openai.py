"""OpenAI-compatible Chat Completions support.

This is the wire format most open-source stacks expose - vLLM, Ollama, TGI's
OpenAI route, llama.cpp's server, LiteLLM, OpenRouter, Together, Groq, and the
Hugging Face router - so one reader covers the whole ecosystem.

Cache accounting differs from Anthropic's and the difference matters:
`usage.prompt_tokens_details.cached_tokens` reports what was served from a
prefix cache, but there is no separate cache-*write* class - nothing is billed
extra to populate the cache. agentprof therefore records cache_write = 0 for
these calls, and the position-based attribution degenerates to
"cached prefix, then full-price remainder", which is exactly how these
endpoints bill.
"""
import json

from .model import block, text_of


def usage(payload):
    """Normalize an OpenAI-compatible `usage` object."""
    u = (payload or {}).get("usage") or {}
    details = u.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0) or 0
    prompt = u.get("prompt_tokens", 0) or 0
    return {
        "input": max(0, prompt - cached),
        "output": u.get("completion_tokens", 0) or 0,
        "cache_read": cached,
        "cache_write": 0,  # no write class in this API
    }


def usage_from_sse(chunks):
    """Usage from a streamed response (needs stream_options.include_usage)."""
    out = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for raw in b"".join(chunks).split(b"\n"):
        if not raw.startswith(b"data: "):
            continue
        body = raw[6:].strip()
        if body == b"[DONE]":
            continue
        try:
            ev = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            continue
        if ev.get("usage"):
            out = usage(ev)
    return out


def _label(name, args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if isinstance(args, dict):
        for k in ("file_path", "path", "command", "pattern", "url", "query", "q", "question"):
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return "%s(%s)" % (name, v.strip().replace("\n", " ")[:60])
        # Tool schemas in the wild use whatever argument names they like (sql,
        # symbol, ticker...), so fall back to the first short string argument.
        for k in sorted(args):
            v = args[k]
            if isinstance(v, str) and v.strip() and len(v) <= 200:
                return "%s(%s)" % (name, v.strip().replace("\n", " ")[:60])
    return name


def blocks(body, state):
    """Split a request into context blocks.

    state carries {tools: {tool_call_id: event_id}, last_llm: id} across calls,
    so a tool result is charged back to the call that requested it.
    """
    out, pending = [], []
    for t in body.get("tools") or []:
        fn = t.get("function") or {}
        name = fn.get("name") or t.get("type") or "tool"
        out.append(block(json.dumps(t, sort_keys=True), "tools", "tool def: " + name, "sys"))

    for msg in body.get("messages") or []:
        role = msg.get("role", "user")
        if role == "system" or role == "developer":
            out.append(block(text_of(msg.get("content")), "system", "system prompt", "sys"))
            continue
        if role == "tool":
            cid = msg.get("tool_call_id")
            tid = state["tools"].get(cid)
            out.append(block(text_of(msg.get("content")), "tool_result",
                             state["labels"].get(cid) or ("result of " + (cid or "tool")), tid))
            continue
        for call in msg.get("tool_calls") or []:
            cid = call.get("id")
            fn = call.get("function") or {}
            name = fn.get("name", "tool")
            tid = state["tools"].get(cid)
            label = _label(name, fn.get("arguments"))
            state["labels"][cid] = label
            if tid is None:
                tid = "t-" + str(cid)
                state["tools"][cid] = tid
                pending.append((tid, name, label))
            out.append(block(json.dumps(call, sort_keys=True), "assistant",
                             "tool call: " + name, state.get("last_llm")))
        txt = text_of(msg.get("content"))
        if txt.strip():
            out.append(block(txt, role, role + " message", state.get("last_llm")))
    return out, pending


def new_state():
    return {"tools": {}, "labels": {}, "last_llm": None}
