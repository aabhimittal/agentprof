# Pricing

## What ships

`agentprof/assets/pricing.json` carries Anthropic's published per-model rates (`as_of` in the file).
Nothing else is bundled, on purpose.

## What happens to everything else

A model with no entry is **unpriced**: cost is zero, token counts stay exact, and the report says so
instead of showing a confident number. The CLI prints a one-line warning and the viewer replaces the
cost tile with `unpriced`, defaults the flamegraph to the *tokens* metric, and ranks the waste table
by tokens re-sent.

This is deliberate. Your vLLM deployment's cost per token is a function of your GPU bill and your
utilisation; an OpenRouter or Together price changes without notice. A profiler that guesses at those
produces authoritative-looking nonsense, and the one thing this tool has to be is trustworthy about
where the money went.

## Supplying your own rates

```json
{
  "models": {
    "meta-llama/Llama-3.3-70B-Instruct": { "in": 0.60, "out": 0.60 },
    "qwen2.5-coder:7b":                  { "in": 0.0,  "out": 0.0  },
    "gpt-4o-mini":                       { "in": 0.15, "out": 0.60, "cache_read": 0.075 }
  }
}
```

```bash
agentprof report run.ndjson --pricing my-prices.json
agentprof summary run.ndjson --pricing my-prices.json
agentprof compare --pricing my-prices.json before.json after.json
```

- Values are **USD per 1M tokens**. `in` and `out` are required.
- `cache_read` defaults to 0.1 × `in`, `cache_write` to 1.25 × `in` — the Anthropic ratios. Set them
  explicitly for providers that bill differently; OpenAI-compatible endpoints have no write class at
  all, so `cache_write` is never charged on those calls regardless of what the table says.
- Matching is exact first, then longest substring, so `"llama-3.3-70b": {...}` covers
  `meta-llama/Llama-3.3-70B-Instruct-Turbo` too.
- For a self-hosted model where you genuinely want a cost view, divide your hourly instance cost by
  the tokens per hour you measure, and put that number in. It will be more accurate than any list
  price agentprof could have shipped.

## Deriving a self-hosted rate

```
$/1M tokens = (instance $/hour ÷ tokens per hour) × 1,000,000
```

Measure tokens per hour from a real workload, not a benchmark — batch size and prefix-cache hit rate
move it by an order of magnitude, which is itself something agentprof will show you.
