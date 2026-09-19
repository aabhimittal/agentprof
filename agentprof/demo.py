"""The synthetic demo run shipped with agentprof.

Numbers are fabricated but internally consistent: usage follows the prefix-cache
rules (cache_read = the prefix carried over, cache_write = whatever is new). It
exists so `agentprof demo` and the web viewer have something to show without
anyone's real transcript.
"""
import json
import random


def lines():
    """Return the demo transcript as a list of JSON lines."""
    random.seed(7)
    MODEL = "claude-opus-5"
    SYSTEM_TOKENS = 14200  # system prompt + tool definitions, invisible in transcripts
    T = [1758240000.0]
    lines_ = []
    hist_tokens = [0]
    prev_billed = [0]
    uid = [0]


    def nid(p="u"):
        uid[0] += 1
        return "%s-%08d" % (p, uid[0])


    def ts(dt):
        T[0] += dt
        import datetime
        return datetime.datetime.utcfromtimestamp(T[0]).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


    def emit(obj):
        lines_.append(json.dumps(obj))


    def add_tokens(text):
        hist_tokens[0] += max(1, len(text) // 4)


    def assistant(content, dt, side=False, cache_break=False):
        billed = SYSTEM_TOKENS + hist_tokens[0]
        if cache_break:
            cache_read, cache_write = 0, billed
        else:
            cache_read = min(prev_billed[0], billed)
            cache_write = billed - cache_read
        prev_billed[0] = billed
        out = sum(max(1, len(json.dumps(c)) // 4) for c in content)
        e = {
            "type": "assistant", "uuid": nid("a"), "parentUuid": None, "isSidechain": side,
            "timestamp": ts(dt), "sessionId": "demo",
            "message": {"role": "assistant", "model": MODEL, "content": content,
                        "usage": {"input_tokens": 0, "output_tokens": out,
                                  "cache_read_input_tokens": cache_read,
                                  "cache_creation_input_tokens": cache_write}},
        }
        emit(e)
        for c in content:
            add_tokens(json.dumps(c))
        return e


    def user(content, dt, side=False):
        emit({"type": "user", "uuid": nid("u"), "parentUuid": None, "isSidechain": side,
              "timestamp": ts(dt), "sessionId": "demo",
              "message": {"role": "user", "content": content}})
        for c in content:
            add_tokens(json.dumps(c))


    def tool_use(name, inp):
        return {"type": "tool_use", "id": nid("tu"), "name": name, "input": inp}


    def tool_result(tu, text):
        return {"type": "tool_result", "tool_use_id": tu["id"], "content": [{"type": "text", "text": text}]}


    ENGINE = ("# engine.py\n" + "def step(state):\n    return state\n" * 260)          # ~12 KB
    TESTLOG = ("FAILED tests/test_engine.py::test_rollback - AssertionError\n" * 40)   # ~3 KB
    SCHEMA = ("column,type,nullable\n" + "field_%d,text,yes\n" * 1 * 300)              # ~6 KB

    user([{"type": "text", "text": "tests/test_engine.py::test_rollback is failing. Find the cause and fix it."}], 0)

    plan = [("Grep", {"pattern": "def rollback", "path": "src"}, "src/engine.py:118:def rollback(self):\n"),
            ("Read", {"file_path": "src/engine.py"}, ENGINE),
            ("Bash", {"command": "pytest tests/test_engine.py -x"}, TESTLOG)]
    for i, (name, inp, res) in enumerate(plan):
        tu = tool_use(name, inp)
        assistant([{"type": "text", "text": "Let me look at %s." % name}, tu], 3.4 + i)
        user([tool_result(tu, res)], 1.2)

    # a subagent explores the schema
    task = tool_use("Task", {"description": "map the persistence schema", "subagent_type": "Explore"})
    assistant([{"type": "text", "text": "Delegating schema exploration."}, task], 4.1)
    for i in range(4):
        stu = tool_use("Read", {"file_path": "db/schema_%d.csv" % i})
        assistant([{"type": "text", "text": "reading schema %d" % i}, stu], 2.6, side=True)
        user([tool_result(stu, SCHEMA)], 0.9, side=True)
    assistant([{"type": "text", "text": "Schema mapped: rollback writes to journal table."}], 3.0, side=True)
    user([tool_result(task, "Subagent report: rollback writes to the journal table without a txn guard.")], 0.4)

    # the expensive loop: same file re-read after every edit
    for i in range(8):
        tu = tool_use("Read", {"file_path": "src/engine.py"})
        assistant([{"type": "text", "text": "Re-reading engine.py after the edit."}, tu], 2.8)
        user([tool_result(tu, ENGINE)], 1.1)
        etu = tool_use("Edit", {"file_path": "src/engine.py", "old_string": "return state", "new_string": "return state.copy()"})
        assistant([{"type": "text", "text": "Applying fix attempt %d." % (i + 1)}, etu], 3.1)
        user([tool_result(etu, "Edit applied to src/engine.py")], 0.6)
        btu = tool_use("Bash", {"command": "pytest tests/test_engine.py -x"})
        assistant([{"type": "text", "text": "Running the test."}, btu], 2.4)
        user([tool_result(btu, TESTLOG if i < 6 else "1 passed in 2.31s")], 4.0)
        if i == 4:  # auto-compaction drops the early history and the prefix cache with it
            hist_tokens[0] = 0
            emit({"type": "user", "uuid": nid("u"), "parentUuid": None, "isSidechain": False,
                  "isCompactSummary": True, "timestamp": ts(1.0), "sessionId": "demo",
                  "message": {"role": "user", "content": [{"type": "text", "text":
                   "Summary of the session so far: engine.py rollback lacks a txn guard; "
                   "8 edit/test cycles attempted; tests still failing on test_rollback."}]}})
            add_tokens("summary" * 120)
            assistant([{"type": "text", "text": "Continuing after compaction."}], 6.0, cache_break=True)

    assistant([{"type": "text", "text": "Fixed: rollback now copies state inside the txn guard. Tests pass."}], 3.2)
    return lines_
