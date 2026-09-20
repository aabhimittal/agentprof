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



def test_observations_are_serialised(tmp_path):
    """Recorder state (ids, the tool map, the file) is shared across request threads.

    CPython's GIL hides the read-modify-write window most of the time, so this
    asserts the invariant directly: no observation may begin while another is in
    flight. Without the lock in observe(), the sleep below guarantees overlap.
    """
    import threading
    import time

    class Tracing(Recorder):
        trace = []

        def _observe(self, *a, **k):
            me = threading.current_thread().name
            Tracing.trace.append(("enter", me))
            time.sleep(0.004)
            Tracing.trace.append(("exit", me))
            return Recorder._observe(self, *a, **k)

    rec = Tracing(str(tmp_path / "run.ndjson"))
    usage = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}
    threads = [threading.Thread(target=rec.observe, args=(BODY, usage, 0.0, 1.0), name="t%d" % i)
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    depth = 0
    for kind, _name in Tracing.trace:
        depth += 1 if kind == "enter" else -1
        assert depth <= 1, "two observations overlapped: %r" % (Tracing.trace,)
    assert len(Tracing.trace) == 16


def test_concurrent_calls_produce_one_intact_record_each(tmp_path):
    import json
    import threading

    out = tmp_path / "run.ndjson"
    rec = Recorder(str(out))
    usage = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}
    threads = [threading.Thread(target=rec.observe, args=(BODY, usage, 0.0, 1.0)) for _ in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = [l for l in out.read_text().splitlines() if l.strip()]
    calls = [json.loads(l) for l in lines]  # a torn write would raise here
    ids = [c["id"] for c in calls if c["kind"] == "llm"]
    assert len(ids) == 24 and len(set(ids)) == 24
