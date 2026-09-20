"""Synthetic example runs, one per agent shape, used by the demo gallery.

These are fabricated but internally consistent: token counts follow from the
bytes actually placed in the context, and cache accounting follows the rules of
the API being imitated (Anthropic's explicit cache_creation/cache_read, or the
OpenAI-compatible `prompt_tokens_details.cached_tokens` with no write class).

They exist so the gallery can show what each finding looks like without anyone
publishing a real transcript. The coding-agent example is a Claude Code
transcript (see demo.py); the rest are OpenAI-compatible logs, which is what
vLLM, Ollama, TGI, LiteLLM, OpenRouter and the HF router all emit.
"""
import json

TOK = 4  # bytes per token, the same estimate the analyzer uses


class Chat(object):
    """Accumulates an OpenAI-compatible conversation and emits request/response pairs."""

    def __init__(self, model, system, prefix_cache=True, t0=1758240000.0):
        self.model = model
        self.msgs = [{"role": "system", "content": system}]
        self.tools = []
        self.lines = []
        self.prefix_cache = prefix_cache
        self.prev_prompt = 0
        self.t = t0
        self.n = 0

    def tool(self, name, description="", **params):
        self.tools.append({"type": "function", "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": params}}})
        return self

    def _prompt_tokens(self):
        size = sum(len(json.dumps(m)) for m in self.msgs) + sum(len(json.dumps(t)) for t in self.tools)
        return max(1, size // TOK)

    def turn(self, text, calls=(), out_tokens=60, seconds=2.0, cache_break=False):
        """One model call. `calls` is a list of (id, name, arguments, result)."""
        self.n += 1
        prompt = self._prompt_tokens()
        cached = 0 if (cache_break or not self.prefix_cache) else min(self.prev_prompt, prompt)
        self.prev_prompt = prompt
        req = {"model": self.model, "tools": list(self.tools), "messages": [dict(m) for m in self.msgs]}
        res = {"model": self.model, "usage": {
            "prompt_tokens": prompt, "completion_tokens": out_tokens,
            "total_tokens": prompt + out_tokens,
            "prompt_tokens_details": {"cached_tokens": cached}}}
        t0 = self.t
        self.t += seconds
        self.lines.append(json.dumps({"request": req, "response": res, "t0": t0, "t1": self.t}))

        assistant = {"role": "assistant", "content": text}
        if calls:
            assistant["tool_calls"] = [
                {"id": cid, "type": "function",
                 "function": {"name": name, "arguments": json.dumps(args)}}
                for cid, name, args, _result in calls]
        self.msgs.append(assistant)
        for cid, _name, _args, result in calls:
            self.msgs.append({"role": "tool", "tool_call_id": cid, "content": result})
            self.t += 0.4
        return self

    def drop_tool_results(self, keep_last=1):
        """Context hygiene: forget stale tool output instead of re-sending it."""
        seen = 0
        kept = []
        for m in reversed(self.msgs):
            if m.get("role") == "tool":
                seen += 1
                if seen > keep_last:
                    continue
            kept.append(m)
        self.msgs = list(reversed(kept))
        return self

    def out(self):
        return self.lines


def _doc(n, kb):
    return ("[doc %d]\n" % n) + ("retrieved passage about the billing subsystem. " * (kb * 1024 // 46))


def rag_research():
    """Retrieval agent that re-sends every chunk it has ever retrieved."""
    c = Chat("claude-sonnet-5", "You answer questions from the knowledge base. " * 30)
    c.tool("search", "semantic search", query={"type": "string"})
    for i in range(9):
        chunks = "\n\n".join(_doc(j, 4) for j in range(i % 3, i % 3 + 3))
        c.turn("Searching for more context on step %d." % (i + 1),
               [("s%d" % i, "search", {"query": "how does billing retry work (%d)" % i}, chunks)],
               out_tokens=90, seconds=2.6)
    c.turn("Billing retries use exponential backoff capped at 5 attempts.", out_tokens=320, seconds=4.0)
    return c.out()


def support_triage():
    """High volume, tiny answers: the fixed prefix is the entire bill."""
    policy = "Support policy. " * 2400  # ~38 KB of instructions on every call
    c = Chat("claude-haiku-4-5", policy)
    c.tool("lookup_order", "fetch an order", order_id={"type": "string"})
    for i in range(24):
        c.turn("Ticket %d: checking the order." % (i + 1),
               [("o%d" % i, "lookup_order", {"order_id": "ORD-%04d" % (7000 + i)},
                 json.dumps({"order": 7000 + i, "status": "shipped", "eta": "2 days"}))],
               out_tokens=45, seconds=1.1)
        c.drop_tool_results(keep_last=0)  # each ticket is independent
    return c.out()


def oss_selfhosted():
    """A self-hosted Llama agent behind vLLM - no published price, so tokens only."""
    c = Chat("meta-llama/Llama-3.3-70B-Instruct", "You are a data engineering assistant. " * 40)
    c.tool("run_sql", "run a read-only query", sql={"type": "string"})
    schema = "column,type,nullable\n" + ("field_%d,text,yes\n" % 1) * 900  # ~12 KB
    for i in range(7):
        c.turn("Inspecting the warehouse schema, pass %d." % (i + 1),
               [("q%d" % i, "run_sql", {"sql": "describe table events_%d" % i}, schema)],
               out_tokens=70, seconds=3.2)
    c.turn("The events table is missing a partition key on ingested_at.", out_tokens=180, seconds=3.0)
    return c.out()


def multi_agent():
    """Orchestrator that fans work out to four workers."""
    c = Chat("claude-opus-5", "You coordinate specialist agents. " * 25)
    c.tool("delegate", "hand a task to a worker", task={"type": "string"})
    for i, task in enumerate(["map the schema", "audit the migrations",
                              "read the deploy config", "summarise the incident log"]):
        worker_report = ("worker %d findings. " % i) * 700  # ~14 KB back from each worker
        c.turn("Delegating: %s." % task,
               [("d%d" % i, "delegate", {"task": task}, worker_report)],
               out_tokens=110, seconds=5.5)
    c.turn("Consolidated: the migration and the deploy config disagree on the partition key.",
           out_tokens=400, seconds=4.5)
    return c.out()


def clean_run():
    """A run doing everything right - the gallery needs a control case."""
    c = Chat("claude-sonnet-5", "You are a concise release assistant.")
    c.tool("changelog", "read the changelog since a tag", since={"type": "string"})
    c.turn("Reading the changelog once.",
           [("c0", "changelog", {"since": "v0.4.0"}, "- fix: retry backoff\n- feat: parquet export\n")],
           out_tokens=140, seconds=2.2)
    c.turn("Drafting the release note.", out_tokens=260, seconds=3.1)
    c.turn("Release note ready.", out_tokens=90, seconds=1.4)
    return c.out()


EXAMPLES = {
    "rag-research": (
        "RAG / research agent",
        "Nine retrieval rounds that never drop a chunk: every passage ever fetched rides along on "
        "every later call, and three of them are byte-identical.",
        rag_research, "openai"),
    "support-triage": (
        "Support triage at volume",
        "Twenty-four independent tickets with 45-token answers. Context hygiene is perfect - and the "
        "38 KB policy prompt still dominates the bill, because it is paid 24 times.",
        support_triage, "openai"),
    "oss-selfhosted": (
        "Self-hosted Llama (vLLM)",
        "An OpenAI-compatible endpoint with no published price. agentprof reports exact tokens and "
        "refuses to invent dollars - supply rates with --pricing to add them.",
        oss_selfhosted, "openai"),
    "multi-agent": (
        "Multi-agent fan-out",
        "An orchestrator delegating to four workers, each returning a 14 KB report that the "
        "orchestrator then carries for the rest of the run.",
        multi_agent, "openai"),
    "clean-run": (
        "A run with nothing wrong",
        "Three calls, one tool result, no duplication, no cache breaks. The control case: agentprof "
        "should find nothing, and does.",
        clean_run, "openai"),
}
