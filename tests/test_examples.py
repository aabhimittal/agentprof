"""Every bundled example must parse, profile and conserve its own totals."""
import pytest

from agentprof.analyze import analyze
from agentprof.demo import lines as coding_agent
from agentprof.examples import EXAMPLES
from agentprof.ingest import read_auto

ALL = [("coding-agent", coding_agent, "claude-code")] + \
      [(name, spec[2], spec[3]) for name, spec in EXAMPLES.items()]


@pytest.mark.parametrize("name,gen,expected_fmt", ALL, ids=[a[0] for a in ALL])
def test_example_profiles_cleanly(name, gen, expected_fmt, tmp_path):
    p = tmp_path / (name + ".jsonl")
    p.write_text("\n".join(gen()) + "\n")
    fmt, events = read_auto(str(p))
    assert fmt == expected_fmt
    prof = analyze(events, source=name)

    t = prof["totals"]
    assert t["calls"] >= 3
    assert t["billed_in"] > 0
    assert prof["tree"]["total"]["cost"] == pytest.approx(t["cost"], rel=1e-6)
    assert prof["tree"]["total"]["tok"] > 0


def test_the_control_case_finds_nothing(tmp_path):
    from agentprof.examples import clean_run

    p = tmp_path / "clean.jsonl"
    p.write_text("\n".join(clean_run()) + "\n")
    prof = analyze(read_auto(str(p))[1], source="clean")
    assert prof["findings"] == [], "a well-behaved run must not be given findings"
    assert prof["waste"] == []


def test_the_scenarios_demonstrate_different_problems(tmp_path):
    """The gallery is only useful if the examples do not all say the same thing."""
    seen = {}
    for name, gen, _fmt in ALL:
        p = tmp_path / (name + ".jsonl")
        p.write_text("\n".join(gen()) + "\n")
        prof = analyze(read_auto(str(p))[1], source=name)
        seen[name] = {f["id"].split("-")[0] for f in prof["findings"]}
    assert seen["clean-run"] == set()
    assert "duplicate" in seen["rag-research"]
    assert "system" in seen["support-triage"]
    assert len({frozenset(v) for v in seen.values()}) >= 4
