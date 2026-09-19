# agentprof

**Flamegraph profiler for agent token spend.** Point it at an agent run and it tells you where the
money went: which tool result got re-sent eighty times, which prefix break threw away your cache,
and how much of the bill is context the model never needed twice.

Local-only. No backend, no account, no telemetry — one self-contained HTML file you can open,
attach to a PR, or email.

[**Live demo**](https://aabhimittal.github.io/agentprof/) · [Sample report](https://aabhimittal.github.io/agentprof/report.html) · MIT

![agentprof report](docs/images/hero.png)

---

## Why

A per-token price feels cheap. A per-*task* price does not: one agent task is 50–200 model calls,
and each call re-sends the whole conversation. A 9 KB file read once is a 9 KB file billed on every
subsequent call until the run ends. Prompt caching hides most of that — until something invalidates
the prefix, and you pay full price to rebuild it.

Existing observability tools (Langfuse and friends) answer *what happened*. agentprof answers
*what it cost you, and because of whom* — with no server to run.

## Quickstart

```bash
pipx install git+https://github.com/aabhimittal/agentprof    # PyPI release pending

agentprof report --open                # profiles the newest Claude Code session for this directory
agentprof summary                      # the same numbers, in the terminal
agentprof export -o agentprof.json     # profile JSON for the web viewer
```

To profile *any* agent that talks to the Anthropic Messages API, put the recording proxy in front:

```bash
agentprof proxy --out run.ndjson &
ANTHROPIC_BASE_URL=http://127.0.0.1:8788 python your_agent.py
agentprof report run.ndjson --open
```

The proxy sees the rendered request, so the system prompt and tool definitions are measured instead
of inferred. It writes hashes, sizes and labels — never your prompt text — to the NDJSON file.

![terminal summary](docs/images/terminal.png)

## What you get

### Attribution flamegraph

![flamegraph](docs/images/flamegraph.png)

Not a timeline — an *attribution* graph, like an allocation flamegraph. A frame's width is what the
run spent **because of** that node, including every later re-send of the context it introduced.
The `Read(src/engine.py)` frame is wide because that file kept being billed for the rest of the run,
not because the read itself was slow. Switch the metric to **tokens** or **time**, click to zoom,
type in the box to highlight.

The `system + tools (inferred)` frame is usually the first surprise: in Claude Code sessions it is
routinely 30–50% of the bill and is invisible in the transcript.

### Prefix cache, call by call

![cache](docs/images/cache.png)

Per call: how much was read from cache (green), written to cache (amber), and billed at full input
price (orange). When the prefix breaks, agentprof diffs the block sequence against the previous call
and names the **first block that changed** — compaction, a re-ordered tool list, an edited system
prompt — plus what re-caching cost.

### Waste attribution

![waste](docs/images/waste.png)

Every context block, fingerprinted and ranked by what its repeat billing cost:

> `Read(src/engine.py)` — 8.6 KB, **6 identical copies in a single request**, billed 80 times,
> $0.19 = 24% of the run.

"Copies in one request" is the sharpest signal in the table: it means the same bytes are sitting in
your context several times over, which no cache discount fixes.

## How the numbers are computed

- **Usage totals and prices are exact.** They come from the provider's `usage` fields and
  [`agentprof/assets/pricing.json`](agentprof/assets/pricing.json).
- **Per-block token counts are estimated** at ~4 bytes/token. agentprof does not ship a tokenizer;
  block-level costs are apportioned, not billed amounts. When the estimate for a request exceeds the
  reported input total, blocks are scaled to fit it.
- **Cost is attributed by prompt position**, which is how prefix caching actually bills: the first
  `cache_read_input_tokens` of a request are charged at the cache-read rate, the next
  `cache_creation_input_tokens` at the write rate, the remainder at full input price. Each block's
  cost is the integral of that rate function over its span, charged back to whatever put it in the
  context.
- **Durations from transcripts are inferred** from the gaps between entries (one timestamp per
  entry is all a transcript has); gaps over 10 minutes are treated as idle, not latency. The proxy
  measures real request duration.

### What agentprof deliberately does *not* claim

It does not tell you what share of your input tokens the model "never attended to". Attention
weights are not exposed by any hosted API, and any number claiming otherwise is inferred from
something else. agentprof reports what is actually measurable: bytes you paid for more than once,
duplicate copies within one request, and cache misses.

## Supported inputs

| Source | How | Fidelity |
|---|---|---|
| Claude Code sessions | `agentprof report` (auto-finds `~/.claude/projects/**/*.jsonl`) | conversation is exact; system prompt + tool defs recovered as a residual |
| Any Anthropic Messages API agent | `agentprof proxy` → NDJSON | exact request composition, real latency |
| Anything else | emit the [NDJSON event format](agentprof/model.py) yourself | whatever you record |

OpenAI-style logs are not supported yet. The normalized event model is small and provider-agnostic;
a reader is ~120 lines (see [`agentprof/ingest/claude_code.py`](agentprof/ingest/claude_code.py)).

## Honest limitations

- **Cache attribution is provider-shaped.** It models Anthropic prefix caching. Providers that cache
  differently (or change their billing fields) will need the model updated — this is the part of
  agentprof most likely to break.
- **Token estimates are estimates.** Ranking is reliable; a single block's dollar figure is not
  invoice-grade.
- **Transcript mode cannot see what the transcript does not contain.** The system prompt and tool
  definitions show up as one inferred block. Use the proxy when you need them broken out.
- **This is not an observability platform.** No traces across services, no evals, no dashboards, no
  history. If you want a hosted product, Langfuse does that well. agentprof's slice is zero-setup
  local profiling of a single run, and it intends to stay that size.

## Deploy your own viewer

The site is static and built from the same assets the CLI embeds, so the viewer can never drift from
the generator:

```bash
python3 tools/build_site.py     # -> ./site (index.html, core.js, core.css, demo.json, report.html)
python3 -m http.server -d site  # http://localhost:8000
```

- **GitHub Pages** — `.github/workflows/pages.yml` builds and deploys on push to `main`
  (enable Pages → *Source: GitHub Actions* once, in repository settings).
- **Vercel** — `vercel.json` is committed; import the repo, no configuration needed.

Step-by-step, including what each target needs you to click once: [docs/DEPLOY.md](docs/DEPLOY.md).
- **Hugging Face Space** — `.github/workflows/hf-space.yml` pushes `site/` to a static Space when an
  `HF_TOKEN` secret is present.

## Development

```bash
python3 tools/make_demo.py      # regenerate the synthetic demo transcript
python3 -m pytest -q            # tests (stdlib only, no fixtures to install)
python3 tools/shots.py          # regenerate docs/images with headless Chromium
```

No runtime dependencies, Python 3.9+, stdlib only — that is a deliberate constraint, so that
installing agentprof is always faster than reading its docs.

## License

MIT © Abhishek Mittal
