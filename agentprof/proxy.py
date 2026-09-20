"""Recording proxy for the Anthropic Messages API.

    agentprof proxy --out run.ndjson
    ANTHROPIC_BASE_URL=http://127.0.0.1:8788 python your_agent.py
    agentprof report run.ndjson

Unlike a transcript, the proxy sees the rendered request, so the system prompt
and tool definitions are measured rather than inferred. Bodies are parsed in
memory and only sizes, hashes and labels are written to disk - the NDJSON never
contains your prompt text.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .model import block, llm_event, text_of, tool_event

UPSTREAM = os.environ.get("ANTHROPIC_UPSTREAM", "https://api.anthropic.com")
HOP = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}


class Recorder(object):
    """Turns observed request/response pairs into normalized events."""

    def __init__(self, path):
        self.path = path
        self.n = 0
        self.tools = {}       # tool_use_id -> event id
        self.last_llm = None
        # ThreadingHTTPServer runs concurrent requests; ids, the tool map and the
        # output file are all shared, so every observation is serialised.
        self.lock = threading.Lock()

    def _write(self, ev):
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, separators=(",", ":")) + "\n")

    def blocks_of(self, body):
        out = []
        sysmsg = body.get("system")
        if sysmsg:
            out.append(block(text_of(sysmsg), "system", "system prompt", "sys"))
        for t in body.get("tools") or []:
            name = t.get("name") or t.get("type") or "tool"
            out.append(block(json.dumps(t, sort_keys=True), "tools", "tool def: " + name, "sys"))
        pending = []
        for msg in body.get("messages") or []:
            content = msg.get("content")
            items = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            for b in items:
                if not isinstance(b, dict):
                    b = {"type": "text", "text": str(b)}
                bt = b.get("type")
                if bt == "tool_use":
                    tid = self.tools.get(b.get("id"))
                    if tid is None:
                        tid = "t-" + str(b.get("id"))
                        self.tools[b.get("id")] = tid
                        pending.append((tid, b.get("name", "tool"), _label(b)))
                    out.append(block(text_of([b]), "assistant", "tool call: " + b.get("name", "tool"), self.last_llm))
                elif bt == "tool_result":
                    tid = self.tools.get(b.get("tool_use_id"))
                    out.append(block(text_of(b.get("content")), "tool_result",
                                     "result of " + (b.get("tool_use_id") or "tool"), tid))
                else:
                    out.append(block(text_of([b]), msg.get("role", "user"), msg.get("role", "user") + " message", self.last_llm))
        return out, pending

    def observe(self, body, usage, t0, t1):
        with self.lock:
            return self._observe(body, usage, t0, t1)

    def _observe(self, body, usage, t0, t1):
        self.n += 1
        eid = "call-%d" % self.n
        blocks, pending = self.blocks_of(body)
        for tid, name, label in pending:
            self._write(tool_event(tid, self.last_llm, t0, t0, name, label, 0))
        self._write(llm_event(eid, None, t0, t1, body.get("model"), usage, blocks, "call %d" % self.n))
        self.last_llm = eid
        return eid


def _label(b):
    inp = b.get("input") or {}
    name = b.get("name", "tool")
    if isinstance(inp, dict):
        for k in ("file_path", "path", "command", "pattern", "url", "query"):
            if isinstance(inp.get(k), str):
                return "%s(%s)" % (name, inp[k][:60])
    return name


def _usage_from(payload):
    u = (payload or {}).get("usage") or {}
    return {
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
    }


def _usage_from_sse(chunks):
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for raw in b"".join(chunks).split(b"\n"):
        if not raw.startswith(b"data: "):
            continue
        try:
            ev = json.loads(raw[6:].decode("utf-8", "replace"))
        except ValueError:
            continue
        if ev.get("type") == "message_start":
            usage.update(_usage_from(ev.get("message")))
        elif ev.get("type") == "message_delta":
            u = _usage_from(ev)
            for k in usage:
                if u.get(k):
                    usage[k] = u[k]
    return usage


def make_handler(rec, verbose=True):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            self._proxy(b"")

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            self._proxy(self.rfile.read(n) if n else b"")

        def _proxy(self, payload):
            url = UPSTREAM.rstrip("/") + self.path
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            req = urllib.request.Request(url, data=payload or None, headers=headers, method=self.command)
            t0 = time.time()
            try:
                resp = urllib.request.urlopen(req, timeout=900)
            except urllib.error.HTTPError as e:
                resp = e
            except Exception as e:  # network failure: report it to the client
                self.send_response(502)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() in HOP:
                    continue
                self.send_header(k, v)
            streaming = "event-stream" in (resp.headers.get("content-type") or "")
            body = []
            if streaming:
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    body.append(chunk)
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            else:
                raw = resp.read()
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                body = [raw]
            t1 = time.time()

            if self.path.endswith("/messages") and self.command == "POST" and resp.status < 300:
                try:
                    reqbody = json.loads(payload.decode("utf-8"))
                    usage = _usage_from_sse(body) if streaming else _usage_from(json.loads(b"".join(body).decode("utf-8")))
                    eid = rec.observe(reqbody, usage, t0, t1)
                    if verbose:
                        sys.stderr.write("[agentprof] %s  in=%d cached=%d out=%d  %.1fs\n" % (
                            eid, usage["input"], usage["cache_read"], usage["output"], t1 - t0))
                except Exception as e:
                    sys.stderr.write("[agentprof] could not record call: %s\n" % e)

    return Handler


def serve(out, host="127.0.0.1", port=8788, verbose=True):
    rec = Recorder(out)
    srv = ThreadingHTTPServer((host, port), make_handler(rec, verbose))
    sys.stderr.write(
        "[agentprof] recording to %s\n[agentprof] point your agent at:  "
        "ANTHROPIC_BASE_URL=http://%s:%d\n[agentprof] ctrl-c to stop, then:  agentprof report %s\n"
        % (out, host, port, out))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[agentprof] stopped after %d calls -> %s\n" % (rec.n, out))
    return rec
