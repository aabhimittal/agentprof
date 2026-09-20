"""The OpenAI-compatible path: vLLM, Ollama, TGI, LiteLLM, OpenRouter, HF router."""
import json

import pytest

from agentprof import fmt_openai
from agentprof.analyze import analyze
from agentprof.ingest import read_auto
from agentprof.ingest.openai_log import sniff

REQ = {
    "model": "meta-llama/Llama-3.3-70B-Instruct",
    "tools": [{"type": "function", "function": {"name": "run_sql", "parameters": {}}}],
    "messages": [
        {"role": "system", "content": "you are a data agent " * 30},
        {"role": "user", "content": "describe the events table"},
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "run_sql", "arguments": json.dumps({"sql": "describe events"})}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "col,type\n" * 400},
    ],
}
RES = {"model": "meta-llama/Llama-3.3-70B-Instruct",
       "usage": {"prompt_tokens": 5000, "completion_tokens": 120,
                 "prompt_tokens_details": {"cached_tokens": 4096}}}


def test_cached_tokens_become_cache_reads_with_no_write_class():
    u = fmt_openai.usage(RES)
    assert u == {"input": 904, "output": 120, "cache_read": 4096, "cache_write": 0}


def test_usage_survives_a_missing_details_block():
    assert fmt_openai.usage({"usage": {"prompt_tokens": 10, "completion_tokens": 2}}) == {
        "input": 10, "output": 2, "cache_read": 0, "cache_write": 0}


def test_streamed_usage_comes_from_the_final_chunk():
    sse = (b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
           b'data: {"usage":{"prompt_tokens":700,"completion_tokens":9,'
           b'"prompt_tokens_details":{"cached_tokens":640}}}\n\n'
           b'data: [DONE]\n\n')
    assert fmt_openai.usage_from_sse([sse]) == {"input": 60, "output": 9, "cache_read": 640, "cache_write": 0}


def test_request_splits_into_attributable_blocks():
    blocks, pending = fmt_openai.blocks(REQ, fmt_openai.new_state())
    kinds = [b["kind"] for b in blocks]
    assert kinds[0] == "tools" and "system" in kinds and "tool_result" in kinds
    assert pending == [("t-c1", "run_sql", "run_sql(describe events)")]
    result = [b for b in blocks if b["kind"] == "tool_result"][0]
    assert result["origin"] == "t-c1"


def test_a_captured_log_is_sniffed_and_profiled(tmp_path):
    p = tmp_path / "run.jsonl"
    rows = []
    for i in range(3):
        res = json.loads(json.dumps(RES))
        res["usage"]["prompt_tokens"] = 5000 + 1000 * i
        res["usage"]["prompt_tokens_details"]["cached_tokens"] = 4096 * (i > 0)
        rows.append(json.dumps({"request": REQ, "response": res, "t0": i, "t1": i + 1.5}))
    p.write_text("\n".join(rows))

    assert sniff(str(p)) == "openai"
    fmt, events = read_auto(str(p))
    assert fmt == "openai"
    prof = analyze(events, source="run.jsonl")
    assert prof["totals"]["calls"] == 3
    assert prof["totals"]["cache_read"] == 4096 * 2
    assert prof["tree"]["total"]["tok"] > 0


def test_proxy_records_openai_calls(tmp_path):
    from agentprof.proxy import Recorder

    out = tmp_path / "run.ndjson"
    rec = Recorder(str(out))
    rec.observe(REQ, fmt_openai.usage(RES), 1.0, 2.0, "openai")
    events = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    kinds = [e["kind"] for e in events]
    assert kinds.count("tool") == 1 and kinds.count("llm") == 1
    llm = [e for e in events if e["kind"] == "llm"][0]
    assert llm["usage"]["cache_read"] == 4096
    assert "you are a data agent" not in out.read_text()  # hashes and sizes only


def test_unmatched_files_still_fall_back_to_the_transcript_reader(tmp_path):
    p = tmp_path / "weird.jsonl"
    p.write_text('{"type":"assistant","uuid":"a1","timestamp":"2026-09-19T10:00:00.000Z",'
                 '"message":{"role":"assistant","model":"claude-opus-5","content":[],'
                 '"usage":{"input_tokens":5,"output_tokens":2}}}\n')
    fmt, events = read_auto(str(p))
    assert fmt == "claude-code" and len(events) == 1
