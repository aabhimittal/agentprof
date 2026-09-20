# Profiling an open-source agent

agentprof records at the HTTP boundary, so it does not care which framework you use — only
which wire format your endpoint speaks. Two are supported:

| Wire format | Who speaks it | How agentprof sees the cache |
|---|---|---|
| Anthropic Messages | Claude API, Claude Code | `cache_creation_input_tokens` + `cache_read_input_tokens` — explicit writes and reads |
| OpenAI Chat Completions | vLLM, Ollama, TGI, llama.cpp, LiteLLM, OpenRouter, Together, Groq, Fireworks, the Hugging Face router, OpenAI itself | `prompt_tokens_details.cached_tokens` — reads only; nothing is billed to populate the cache |

> The proxy path is covered end-to-end in CI (`tests/test_proxy_e2e.py` drives the real proxy against
> a fake OpenAI-compatible server, streaming and non-streaming). The individual server commands below
> are configuration, not code paths — they have not been executed in this repository's CI.

## vLLM

```bash
vllm serve meta-llama/Llama-3.3-70B-Instruct --enable-prefix-caching   # prefix caching on
agentprof proxy --upstream http://127.0.0.1:8000 --out run.ndjson &

OPENAI_BASE_URL=http://127.0.0.1:8788/v1 OPENAI_API_KEY=x python your_agent.py
agentprof report run.ndjson --open
```

Without `--enable-prefix-caching` every call reports `cached_tokens: 0`, and agentprof will
(correctly) tell you the cache hit rate is zero — which is the finding.

## Ollama

```bash
ollama serve
agentprof proxy --upstream http://127.0.0.1:11434 --out run.ndjson &
OPENAI_BASE_URL=http://127.0.0.1:8788/v1 python your_agent.py
```

## LiteLLM, OpenRouter, Together, Groq, Fireworks, HF router

Anything with an OpenAI-compatible base URL works the same way — point `--upstream` at the provider
and your agent at the proxy:

```bash
agentprof proxy --upstream https://openrouter.ai/api --out run.ndjson &
OPENAI_BASE_URL=http://127.0.0.1:8788/v1 python your_agent.py

agentprof proxy --upstream https://router.huggingface.co/v1 --out run.ndjson &
OPENAI_BASE_URL=http://127.0.0.1:8788/v1 python your_agent.py
```

Your API key rides through in the headers; agentprof does not read, store or log it.

## Frameworks

No integration code is needed — every one of these honours the OpenAI base URL:

| Framework | What to set |
|---|---|
| OpenAI Agents SDK | `OPENAI_BASE_URL=http://127.0.0.1:8788/v1` |
| LangChain / LangGraph | `ChatOpenAI(base_url="http://127.0.0.1:8788/v1", ...)` |
| LlamaIndex | `OpenAILike(api_base="http://127.0.0.1:8788/v1", ...)` |
| CrewAI, AutoGen, smolagents | they use the OpenAI client underneath — set the same env var |
| Claude Agent SDK / Claude Code | `ANTHROPIC_BASE_URL=http://127.0.0.1:8788` |

**Streaming:** the OpenAI API only reports usage on a streamed call when you ask for it. Set
`stream_options={"include_usage": True}`; agentprof warns on stderr when a streamed call arrives
with no usage attached.

## Without the proxy

If you already log requests and responses (a LiteLLM callback, an httpx event hook, three lines
around your client), write them as NDJSON and skip the proxy entirely:

```json
{"request": {"model": "...", "messages": [...], "tools": [...]}, "response": {"usage": {...}}, "t0": 1758240000.0, "t1": 1758240002.4}
```

```bash
agentprof report captured.jsonl
```

`t0`/`t1` are optional epoch seconds — supply them and you get real latency in the flamegraph's
*time* metric. Aliases for the two halves (`req`/`res`, `body`/`output`, …) are accepted.

## Pricing an open-source model

Self-hosted models have no list price, and agentprof will not invent one — see
[PRICING.md](PRICING.md). Runs without known rates report exact tokens and zero dollars, and every
finding switches to token counts, so the analysis still works:

```bash
agentprof report run.ndjson --pricing my-prices.json
```
