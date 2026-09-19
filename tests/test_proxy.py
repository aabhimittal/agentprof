from agentprof.proxy import Recorder, _usage_from_sse

BODY = {
    "model": "claude-opus-5",
    "system": [{"type": "text", "text": "you are a helpful agent " * 40}],
    "tools": [{"name": "read_file", "input_schema": {"type": "object"}}],
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "read a.py"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "tu1", "name": "read_file",
                                           "input": {"file_path": "a.py"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1",
                                      "content": [{"type": "text", "text": "x" * 4096}]}]},
    ],
}


def test_request_is_split_into_attributable_blocks(tmp_path):
    rec = Recorder(str(tmp_path / "run.ndjson"))
    blocks, pending = rec.blocks_of(BODY)
    kinds = [b["kind"] for b in blocks]
    assert kinds[:2] == ["system", "tools"]
    assert "tool_result" in kinds
    assert pending and pending[0][1] == "read_file"
    result = [b for b in blocks if b["kind"] == "tool_result"][0]
    assert result["origin"] == "t-tu1" and result["bytes"] == 4096


def test_observe_writes_events_and_no_prompt_text(tmp_path):
    out = tmp_path / "run.ndjson"
    rec = Recorder(str(out))
    rec.observe(BODY, {"input": 10, "output": 5, "cache_read": 0, "cache_write": 100}, 1.0, 2.5)
    raw = out.read_text()
    assert raw.count("\n") == 2  # one tool event + one llm event
    assert "helpful agent" not in raw and "xxxx" not in raw


def test_usage_is_recovered_from_a_stream():
    sse = (b'event: message_start\ndata: {"type":"message_start","message":{"usage":'
           b'{"input_tokens":7,"cache_read_input_tokens":900}}}\n\n'
           b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":42}}\n\n')
    u = _usage_from_sse([sse])
    assert u == {"input": 7, "output": 42, "cache_read": 900, "cache_write": 0}
