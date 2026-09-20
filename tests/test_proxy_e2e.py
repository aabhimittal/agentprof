"""End-to-end: a real HTTP request through the real proxy to a fake OpenAI server.

This is the evidence behind "works with any OpenAI-compatible endpoint" - vLLM,
Ollama, TGI, LiteLLM and friends all answer exactly this shape. The fake server
is stdlib only, so it runs everywhere CI does.
"""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentprof.analyze import analyze
from agentprof.ingest import read_auto
from agentprof.proxy import Recorder, make_handler

BODY = {
    "model": "qwen2.5-coder:7b",
    "tools": [{"type": "function", "function": {"name": "grep", "parameters": {}}}],
    "messages": [
        {"role": "system", "content": "you are a local agent " * 50},
        {"role": "user", "content": "find the retry logic"},
    ],
}


class FakeUpstream(BaseHTTPRequestHandler):
    """Answers /v1/chat/completions the way a local vLLM or Ollama server does."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        prompt = sum(len(json.dumps(m)) for m in req.get("messages", [])) // 4
        if req.get("stream"):
            chunks = [
                b'data: {"choices":[{"delta":{"content":"found it"}}]}\n\n',
                ('data: {"usage":{"prompt_tokens":%d,"completion_tokens":11,'
                 '"prompt_tokens_details":{"cached_tokens":%d}}}\n\n' % (prompt, prompt // 2)).encode(),
                b'data: [DONE]\n\n',
            ]
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            for c in chunks:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.write(b"0\r\n\r\n")
            return
        payload = json.dumps({
            "model": req.get("model"),
            "choices": [{"message": {"role": "assistant", "content": "found it"}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": 11,
                      "prompt_tokens_details": {"cached_tokens": prompt // 2}},
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


@pytest.fixture
def stack(tmp_path, monkeypatch):
    upstream, upstream_url = _serve(FakeUpstream)
    monkeypatch.setattr("agentprof.proxy.UPSTREAM", upstream_url)
    rec = Recorder(str(tmp_path / "run.ndjson"))
    proxy, proxy_url = _serve(make_handler(rec, verbose=False))
    yield proxy_url, tmp_path / "run.ndjson"
    proxy.shutdown()
    upstream.shutdown()


def _records(path, kind="llm", want=1, timeout=5.0):
    """Wait for the recorder to land `want` events.

    The proxy deliberately writes its record *after* the response has been
    flushed to the client, so profiling never sits in the agent's critical path;
    that makes the write asynchronous from the caller's point of view.
    """
    import time

    deadline = time.time() + timeout
    while True:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] \
            if path.exists() else []
        hits = [e for e in rows if e["kind"] == kind]
        if len(hits) >= want or time.time() > deadline:
            return hits
        time.sleep(0.02)


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=20).read()


def test_a_call_through_the_proxy_reaches_the_server_and_is_recorded(stack):
    proxy_url, out = stack
    raw = _post(proxy_url + "/v1/chat/completions", BODY)

    assert json.loads(raw)["choices"][0]["message"]["content"] == "found it"  # pass-through intact
    llm = _records(out)
    assert len(llm) == 1
    assert llm[0]["usage"]["cache_read"] > 0 and llm[0]["usage"]["output"] == 11
    assert llm[0]["t1"] >= llm[0]["t0"]
    assert "you are a local agent" not in out.read_text()


def test_streamed_calls_are_recorded_and_still_stream(stack):
    proxy_url, out = stack
    raw = _post(proxy_url + "/v1/chat/completions", dict(BODY, stream=True))

    assert b"found it" in raw and raw.rstrip().endswith(b"[DONE]")
    llm = _records(out)
    assert len(llm) == 1 and llm[0]["usage"]["cache_read"] > 0


def test_the_recording_profiles_without_further_help(stack):
    proxy_url, out = stack
    for _ in range(3):
        _post(proxy_url + "/v1/chat/completions", BODY)
    _records(out, want=3)

    fmt, events = read_auto(str(out))
    assert fmt == "ndjson"
    prof = analyze(events, source="run.ndjson")
    assert prof["totals"]["calls"] == 3
    assert prof["totals"]["hit_rate"] > 0
    assert prof["meta"]["unpriced"] == ["qwen2.5-coder:7b"]
