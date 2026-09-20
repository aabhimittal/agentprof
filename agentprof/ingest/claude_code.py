"""Reader for Claude Code session transcripts (~/.claude/projects/**/*.jsonl).

The transcript holds the conversation, not the rendered request, so the system
prompt and tool definitions are not visible here. analyze.py recovers their size
as a residual from reported input token counts (see 'system+tools (inferred)').
Use `agentprof proxy` when you need byte-exact request composition.
"""
import glob
import json
import os
from datetime import datetime

from ..model import block, llm_event, text_of, tool_event


def _ts(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
    except ValueError:
        try:
            return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except ValueError:
            return None


def find_sessions(project_dir=None, root=None):
    """Newest-first list of transcript paths for a project directory."""
    root = root or os.path.expanduser("~/.claude/projects")
    project_dir = os.path.abspath(project_dir or os.getcwd())
    slug = project_dir.replace("/", "-").replace("_", "-").replace(".", "-")
    candidates = sorted(
        glob.glob(os.path.join(root, slug, "*.jsonl"))
        or glob.glob(os.path.join(root, "*", "*.jsonl")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    return candidates


def _label_for(name, inp):
    if not isinstance(inp, dict):
        return name
    for key in ("file_path", "path", "pattern", "command", "url", "description", "query"):
        if key in inp and isinstance(inp[key], str):
            v = inp[key].strip().replace("\n", " ")
            return "%s(%s)" % (name, v[:60])
    for key in sorted(inp):  # MCP and custom tools name their arguments freely
        v = inp[key]
        if isinstance(v, str) and v.strip() and len(v) <= 200:
            return "%s(%s)" % (name, v.strip().replace("\n", " ")[:60])
    return name


def read(path):
    """Parse one transcript into normalized events."""
    events = []
    history = []          # ordered context blocks seen so far
    tool_by_use_id = {}   # tool_use_id -> tool event
    last_task_tool = [None]
    step_n = 0
    prev_step_id = None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            etype = e.get("type")
            if etype == "system" and e.get("subtype") == "compact_boundary":
                history = []  # auto-compaction: the cached prefix is gone
                continue
            if etype not in ("user", "assistant"):
                continue
            msg = e.get("message") or {}
            ts = _ts(e.get("timestamp"))
            content = msg.get("content")
            sidechain = bool(e.get("isSidechain"))

            if etype == "user":
                if e.get("isCompactSummary"):
                    history = []  # auto-compaction: the cached prefix is gone
                # Tool results close out their tool event and enter the context.
                blocks_here = []
                items = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
                for b in items:
                    if not isinstance(b, dict):
                        b = {"type": "text", "text": str(b)}
                    if b.get("type") == "tool_result":
                        tev = tool_by_use_id.get(b.get("tool_use_id"))
                        txt = text_of(b.get("content"))
                        if tev is not None:
                            tev["t1"] = ts or tev["t1"]
                            tev["result_bytes"] = len(txt.encode("utf-8", "replace"))
                            origin, label = tev["id"], tev["label"]
                        else:
                            origin, label = prev_step_id, "tool_result"
                        blocks_here.append(block(txt, "tool_result", label, origin))
                    else:
                        txt = text_of([b])
                        if txt.strip():
                            blocks_here.append(block(txt, "user", "user message", prev_step_id))
                history.extend(blocks_here)
                continue

            # assistant
            usage = msg.get("usage") or {}
            has_usage = any(
                usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
            )
            step_id = e.get("uuid") or ("step%d" % step_n)
            if has_usage:
                step_n += 1
                parent = last_task_tool[0] if sidechain else None
                ev = llm_event(
                    eid=step_id,
                    parent=parent,
                    t0=ts,
                    t1=ts,
                    model=msg.get("model"),
                    usage={
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_write": usage.get("cache_creation_input_tokens", 0),
                    },
                    blocks=list(history),
                    label="step %d%s" % (step_n, " (subagent)" if sidechain else ""),
                )
                events.append(ev)
                prev_step_id = step_id

            # Assistant output joins the context; tool_use blocks open tool events.
            items = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            for b in items:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name = b.get("name", "tool")
                    label = _label_for(name, b.get("input"))
                    tev = tool_event(
                        eid="t-" + str(b.get("id", len(events))),
                        parent=prev_step_id,
                        t0=ts,
                        t1=ts,
                        name=name,
                        label=label,
                        result_bytes=0,
                    )
                    tool_by_use_id[b.get("id")] = tev
                    events.append(tev)
                    if name in ("Task", "Agent"):
                        last_task_tool[0] = tev["id"]
                txt = text_of([b])
                if txt.strip():
                    history.append(block(txt, "assistant", "assistant output", prev_step_id))
    return events
