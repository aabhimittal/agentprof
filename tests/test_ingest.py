from agentprof.ingest import read_auto
from agentprof.ingest.claude_code import _label_for


def test_reads_claude_code_transcript(demo_path):
    fmt, events = read_auto(demo_path)
    assert fmt == "claude-code"
    llms = [e for e in events if e["kind"] == "llm"]
    tools = [e for e in events if e["kind"] == "tool"]
    assert len(llms) == 35 and len(tools) == 32
    assert all(e["usage"]["cache_read"] >= 0 for e in llms)


def test_context_grows_then_resets_at_compaction(demo_path):
    llms = [e for e in read_auto(demo_path)[1] if e["kind"] == "llm"]
    sizes = [len(e["blocks"]) for e in llms]
    assert max(sizes) > 60
    assert min(sizes[1:]) < max(sizes), "compaction should shrink the context"
    drops = [i for i in range(1, len(sizes)) if sizes[i] < sizes[i - 1]]
    assert drops, "expected at least one compaction boundary"


def test_subagent_calls_hang_off_the_task_tool(demo_path):
    events = read_auto(demo_path)[1]
    tasks = [e for e in events if e["kind"] == "tool" and e["name"] == "Task"]
    assert tasks
    children = [e for e in events if e["kind"] == "llm" and e["parent"] == tasks[0]["id"]]
    assert len(children) == 5


def test_tool_labels_pick_the_useful_argument():
    assert _label_for("Read", {"file_path": "src/a.py"}) == "Read(src/a.py)"
    assert _label_for("Bash", {"command": "pytest -x"}) == "Bash(pytest -x)"
    assert _label_for("Weird", {"unknown": 1}) == "Weird"
