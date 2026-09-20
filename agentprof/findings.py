"""Turn the measured profile into a short list of things worth acting on.

Every finding is derived from numbers already in the profile and carries the
evidence with it - no heuristics dressed up as certainties, no advice that the
data does not support. A run with nothing wrong produces an empty list, which
is a valid and useful result.

The dollar figures are what each issue touches, not a partition of the bill:
the same token can belong to two findings (tokens re-written after a prefix
break include the system prefix, which the overhead finding also counts). Where
one finding is strictly contained in another - a duplicated block is also a
re-sent block - the narrower one wins and the other is suppressed.
"""

from .pricing import rates

HIGH, MED, INFO = "high", "medium", "info"


def _recache_premium(steps):
    """What a cache miss actually costs *extra*.

    The whole call cost overlaps with every other finding (it contains the system
    prefix and the re-sent blocks), so charge a break only the difference between
    writing those tokens and having read them from cache.
    """
    total = 0.0
    for s in steps:
        r = rates(s.get("model"))
        total += s["usage"]["cache_write"] * (r["cache_write"] - r["cache_read"]) / 1e6
    return total


def _f(fid, level, title, detail, usd=0.0, share=0.0):
    return {"id": fid, "level": level, "title": title, "detail": detail,
            "usd": usd, "share": share}


def findings(totals, steps, blocks, sys_cost, sub_cost):
    """blocks: every fingerprinted context block (not just the listed ones).

    An unpriced run (self-hosted, or a model with no rates supplied) still has
    exact token counts, so every threshold below switches to tokens and the
    impact figures are reported in tokens instead of dollars.
    """
    out = []
    priced = totals.get("priced", True) and totals["cost"] > 0
    cost = (totals["cost"] if priced else float(totals.get("billed_in") or 0)) or 1e-12
    repeat = (lambda b: b["repeat_cost"]) if priced else (lambda b: b["repeat_tok"])
    calls = totals["calls"]
    if not calls:
        return out

    # 1. The same bytes sitting in one request several times over. No cache
    #    discount removes this - you are billed per copy, per call.
    dups = sorted([b for b in blocks if b["dup_max"] > 1 and b["bytes"] >= 512],
                  key=lambda b: -repeat(b))
    if dups:
        d = dups[0]
        total_dup = sum(repeat(b) for b in dups)
        detail = (
            "%s is %.1f KB and appears %d times in one prompt, across %d requests. "
            "Re-reading a file you already have in context is the usual cause; "
            "de-duplicate tool results, or re-read only the range that changed."
            % (d["label"], d["bytes"] / 1024.0, d["dup_max"], d["steps"]))
        if len(dups) > 1:
            detail += " %d other block(s) are duplicated the same way." % (len(dups) - 1)
        out.append(_f(
            "duplicate-copies", HIGH,
            "%d identical copies of the same content in a single request" % d["dup_max"],
            detail, total_dup if priced else 0.0, total_dup / cost))

    # 2. One block dominating the bill through repeat billing.
    counted = {b["h"] for b in dups}  # already charged to the duplicate finding
    heavy = [b for b in blocks
             if repeat(b) > 0.05 * cost and b["bytes"] >= 512 and b["h"] not in counted]
    for b in sorted(heavy, key=lambda b: -repeat(b))[:2]:
        out.append(_f(
            "resend-" + b["h"], HIGH,
            "%s was billed %d times" % (b["label"], b["n"]),
            "%.1f KB re-sent on every later call, costing %s (%.0f%% of the run) beyond "
            "its first use. Summarise it, drop it once it stops being relevant, or move the "
            "work to a subagent whose context ends with the task."
            % (b["bytes"] / 1024.0,
               ("$%.4f" % b["repeat_cost"]) if priced else ("%d tokens" % b["repeat_tok"]),
               100 * repeat(b) / cost),
            repeat(b) if priced else 0.0, repeat(b) / cost))

    # 3. Fixed overhead that is paid on literally every call.
    if priced and sys_cost > 0.25 * cost:
        out.append(_f(
            "system-overhead", MED,
            "System prompt and tool definitions are %.0f%% of the run" % (100 * sys_cost / cost),
            "$%.4f went to the fixed prefix - it is re-billed (at cache rates, but re-billed) "
            "on each of the %d calls. Trimming tool definitions or a verbose system prompt "
            "scales across every call you will ever make." % (sys_cost, calls),
            sys_cost, sys_cost / cost))

    # 4. Cache reuse. Below ~70% on a long run, something is invalidating the prefix.
    if calls >= 5 and totals["hit_rate"] < 0.7:
        out.append(_f(
            "low-cache-hit", HIGH,
            "Cache hit rate is %.0f%%" % (100 * totals["hit_rate"]),
            "Only %.0f%% of billed input tokens were cache reads over %d calls. Anything that "
            "changes early in the prompt - a timestamp in the system prompt, a re-ordered tool "
            "list, unsorted JSON - invalidates everything after it."
            % (100 * totals["hit_rate"], calls),
            0.0, 0.0))

    # 5. Prefix breaks, with what the re-caching cost.
    broke = [s for s in steps if s["broke"]]
    if broke and priced:
        recache = _recache_premium(broke)
        first = broke[0]["broke"]
        out.append(_f(
            "prefix-break", MED if len(broke) < 3 else HIGH,
            "%d prefix break%s threw away the cache" % (len(broke), "" if len(broke) == 1 else "s"),
            "The first break dropped %d of %d context blocks, starting at %s. Rebuilding the cache "
            "instead of reading it cost an extra $%.4f. Compaction and edits to earlier turns both "
            "do this; append rather than rewrite where you can."
            % (first["of"] - first["at"], first["of"], first["label"], recache),
            recache, recache / cost))

    # 6. Spending on reading rather than producing.
    if totals["out"] and totals["billed_in"] / float(totals["out"]) > 300:
        out.append(_f(
            "read-vs-write", INFO,
            "%d input tokens billed per output token" % (totals["billed_in"] // totals["out"]),
            "This run paid to re-read context, not to generate. That ratio is normal for a "
            "long tool-using loop, and it is exactly the ratio caching and context hygiene move.",
            0.0, 0.0))

    # 7. A single oversized tool result.
    big = sorted([b for b in blocks if b["kind"] == "tool_result"], key=lambda b: -b["bytes"])
    if big and big[0]["bytes"] > 20 * 1024:
        b = big[0]
        out.append(_f(
            "large-tool-result", MED,
            "One tool result is %.0f KB" % (b["bytes"] / 1024.0),
            "%s returned %.0f KB in one go and was billed %d times. Paginate the tool, or have "
            "it return a summary with an explicit way to fetch detail."
            % (b["label"], b["bytes"] / 1024.0, b["n"]),
            b["cost"] if priced else 0.0, (b["cost"] if priced else b["tok"] * b["n"]) / cost))

    # 8. Subagent share, when it is material.
    if priced and sub_cost > 0.2 * cost:
        out.append(_f(
            "subagent-share", INFO,
            "Subagents account for %.0f%% of the run" % (100 * sub_cost / cost),
            "$%.4f was spent inside delegated tasks. That is often the right trade - their "
            "context is discarded when they finish - but it is worth checking they run on the "
            "cheapest model that does the job." % sub_cost,
            sub_cost, sub_cost / cost))

    order = {HIGH: 0, MED: 1, INFO: 2}
    out.sort(key=lambda f: (order[f["level"]], -f["usd"]))
    return out
