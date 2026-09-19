"""Turn normalized events into a profile: attribution tree, cache report, waste report.

Attribution model
-----------------
Prefix caching bills a request by *position*: the first `cache_read` tokens of
the rendered prompt are charged at the cache-read rate, the next
`cache_write` tokens at the cache-write rate, the rest at the full input rate.
agentprof lays the context blocks out in that same order and integrates the
rate function over each block's token span. A block's cost is therefore charged
back to the event that first put it in the context - the tool call that read a
file pays for every later re-send of that file.

That makes the flamegraph an attribution graph (like an allocation flamegraph),
not a timeline: a node's width is the money the run spent *because of* it.
Token counts per block are estimated at ~4 bytes/token; usage totals are exact.
"""
from .model import TOKENS_PER_BYTE
from .pricing import rates

MAX_GAP_S = 600.0


def _infer_durations(events):
    """Transcripts record one timestamp per entry. Recover spans from the gaps."""
    ordered = sorted([e for e in events if e.get("t0")], key=lambda e: e["t0"])
    prev_end = None
    for e in ordered:
        if e["kind"] == "llm" and (not e.get("t1") or e["t1"] <= e["t0"]):
            start = prev_end if prev_end and 0 <= e["t0"] - prev_end <= MAX_GAP_S else e["t0"]
            e["t1"], e["t0"] = e["t0"], start
        if e["kind"] == "tool" and (not e.get("t1") or e["t1"] < e["t0"]):
            e["t1"] = e["t0"]
        prev_end = max(prev_end or 0, e.get("t1") or 0)


def _rate_at(offset, usage, r):
    """USD per token at token position `offset` of the rendered prompt."""
    if offset < usage["cache_read"]:
        return r["cache_read"] / 1e6
    if offset < usage["cache_read"] + usage["cache_write"]:
        return r["cache_write"] / 1e6
    return r["in"] / 1e6


def _span_cost(start, end, usage, r):
    """Integrate the per-position rate over [start, end) tokens."""
    total = 0.0
    pos = start
    bounds = [usage["cache_read"], usage["cache_read"] + usage["cache_write"], float("inf")]
    for b in bounds:
        if pos >= end:
            break
        seg_end = min(end, b)
        if seg_end > pos:
            total += (seg_end - pos) * _rate_at(pos, usage, r)
            pos = seg_end
    return total


def _node(nid, name, kind):
    return {
        "id": nid,
        "name": name,
        "kind": kind,
        "self": {"cost": 0.0, "tok": 0, "ms": 0.0},
        "total": {"cost": 0.0, "tok": 0, "ms": 0.0},
        "children": [],
        "meta": {},
    }


def analyze(events, source="", max_waste=18, min_bytes=256):
    _infer_durations(events)
    llms = [e for e in events if e["kind"] == "llm"]
    tools = [e for e in events if e["kind"] == "tool"]

    root = _node("root", source or "run", "root")
    sysnode = _node("sys", "system + tools (inferred)", "system")
    nodes = {"root": root, "sys": sysnode}
    for e in llms + tools:
        n = _node(e["id"], e.get("label") or e.get("name") or e["id"], e["kind"])
        n["meta"]["model"] = e.get("model")
        nodes[e["id"]] = n

    # wire the tree
    root["children"].append(sysnode)
    for e in llms + tools:
        parent = nodes.get(e.get("parent")) or root
        parent["children"].append(nodes[e["id"]])

    # durations are real time, charged to the node that spent it
    for e in llms + tools:
        nodes[e["id"]]["self"]["ms"] += max(0.0, ((e.get("t1") or 0) - (e.get("t0") or 0)) * 1000.0)

    steps = []
    waste = {}
    prev_hashes = []
    totals = {"cost": 0.0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0}

    for idx, e in enumerate(llms):
        u = e["usage"]
        r = rates(e["model"])
        billed_in = u["input"] + u["cache_read"] + u["cache_write"]
        blocks = e["blocks"]
        est = [max(1, int(b["bytes"] * TOKENS_PER_BYTE)) for b in blocks]
        known = sum(est)
        residual = billed_in - known
        scale = 1.0
        if residual < 0 and known:
            # our byte estimate overshot; scale blocks to fit the billed total
            scale = billed_in / float(known)
            residual = 0

        per_call = {}
        offset = 0
        if residual > 0:
            c = _span_cost(0, residual, u, r)
            sysnode["self"]["cost"] += c
            sysnode["self"]["tok"] += residual
            offset = residual

        for b, tk in zip(blocks, est):
            tk = max(1, int(tk * scale))
            end = min(billed_in, offset + tk)
            if end <= offset:
                break
            c = _span_cost(offset, end, u, r)
            owner = nodes.get(b["origin"]) or nodes[e["id"]]
            owner["self"]["cost"] += c
            owner["self"]["tok"] += end - offset
            w = waste.setdefault(
                b["h"],
                {"label": b["label"], "kind": b["kind"], "bytes": b["bytes"], "n": 0,
                 "cost": 0.0, "repeat_cost": 0.0, "cached_cost": 0.0, "tok": end - offset,
                 "origin": b["origin"], "first_step": idx, "dup_max": 0, "steps": 0},
            )
            w["n"] += 1
            per_call[b["h"]] = per_call.get(b["h"], 0) + 1
            w["cost"] += c
            if w["n"] > 1:
                w["repeat_cost"] += c
            if offset < u["cache_read"]:
                w["cached_cost"] += c
            offset = end

        for h, c in per_call.items():
            w = waste[h]
            w["dup_max"] = max(w["dup_max"], c)
            w["steps"] += 1

        out_cost = u["output"] * r["out"] / 1e6
        nodes[e["id"]]["self"]["cost"] += out_cost
        nodes[e["id"]]["self"]["tok"] += u["output"]

        hashes = [b["h"] for b in blocks]
        lcp = 0
        while lcp < len(hashes) and lcp < len(prev_hashes) and hashes[lcp] == prev_hashes[lcp]:
            lcp += 1
        broke = None
        if prev_hashes and lcp < len(prev_hashes):
            b = blocks[lcp] if lcp < len(blocks) else None
            broke = {
                "at": lcp,
                "of": len(prev_hashes),
                "label": (b or {}).get("label", "(context truncated)"),
                "kind": (b or {}).get("kind", "?"),
            }
        call_cost = _span_cost(0, billed_in, u, r) + out_cost
        steps.append({
            "id": e["id"], "label": e.get("label"), "model": e["model"],
            "t0": e.get("t0"), "t1": e.get("t1"),
            "ms": max(0.0, ((e.get("t1") or 0) - (e.get("t0") or 0)) * 1000.0),
            "usage": u, "cost": call_cost, "blocks": len(blocks),
            "hit": (u["cache_read"] / float(billed_in)) if billed_in else 0.0,
            "broke": broke,
        })
        totals["cost"] += call_cost
        totals["in"] += u["input"]
        totals["out"] += u["output"]
        totals["cache_read"] += u["cache_read"]
        totals["cache_write"] += u["cache_write"]
        totals["calls"] += 1
        prev_hashes = hashes

    _rollup(root)

    # "never referenced": a tool result whose label never shows up in any later
    # assistant output or tool input. Heuristic, and labelled as one in the UI.
    texts = []
    for e in llms:
        for b in e["blocks"]:
            if b["kind"] in ("assistant", "user"):
                texts.append(b["label"])
    tool_names = {t["id"]: t for t in tools}
    for h, w in waste.items():
        w["h"] = h
        t = tool_names.get(w["origin"])
        w["tool"] = t["name"] if t else None

    for w in waste.values():
        n = nodes.get(w["origin"])
        if n is not None and w["bytes"] > 512:
            mt = n["meta"]
            mt["billed"] = mt.get("billed", 0) + w["n"]
            mt["copies"] = max(mt.get("copies", 0), w["dup_max"])
            mt["bytes"] = max(mt.get("bytes", 0), w["bytes"])

    # Blocks smaller than a line or two of text are noise in a ranking table -
    # they are still counted in the totals, just not listed.
    notable = [w for w in waste.values() if w["bytes"] >= min_bytes]
    waste_list = sorted(notable, key=lambda w: -w["repeat_cost"])
    repeated = [w for w in waste_list if w["n"] > 1][:max_waste]

    billed_total = totals["in"] + totals["cache_read"] + totals["cache_write"]
    resent_cost = sum(w["repeat_cost"] for w in waste.values())
    meta = {
        "source": source,
        "generated": None,
        "duration_s": (max([e.get("t1") or 0 for e in llms + tools] or [0]) -
                       min([e.get("t0") or 0 for e in llms + tools] or [0])),
        "models": sorted({e["model"] for e in llms}),
    }
    return {
        "version": 1,
        "meta": meta,
        "totals": dict(
            totals,
            billed_in=billed_total,
            hit_rate=(totals["cache_read"] / billed_total) if billed_total else 0.0,
            resent_cost=resent_cost,
            resent_share=(resent_cost / totals["cost"]) if totals["cost"] else 0.0,
            tools=len(tools),
        ),
        "tree": root,
        "steps": steps,
        "waste": repeated,
        "top_cost": sorted(notable, key=lambda w: -w["cost"])[:max_waste],
    }


def _rollup(n):
    t = {"cost": n["self"]["cost"], "tok": n["self"]["tok"], "ms": n["self"]["ms"]}
    for c in n["children"]:
        ct = _rollup(c)
        for k in t:
            t[k] += ct[k]
    n["total"] = t
    n["children"].sort(key=lambda c: -c["total"]["cost"])
    return t
