import pytest

from agentprof.analyze import _span_cost, analyze
from agentprof.pricing import cost, rates


def test_totals_match_the_price_table(profile):
    t = profile["totals"]
    expect = cost("claude-opus-5", {
        "input": t["in"], "output": t["out"],
        "cache_read": t["cache_read"], "cache_write": t["cache_write"]})
    assert t["cost"] == pytest.approx(expect, rel=1e-6)


def test_attribution_is_conserved(profile):
    """Every dollar in the totals lands on exactly one node of the tree."""
    assert profile["tree"]["total"]["cost"] == pytest.approx(profile["totals"]["cost"], rel=1e-6)


def test_span_cost_follows_the_cache_boundaries():
    r = rates("claude-opus-5")
    u = {"input": 1000, "output": 0, "cache_read": 1000, "cache_write": 1000}
    assert _span_cost(0, 1000, u, r) == pytest.approx(1000 * r["cache_read"] / 1e6)
    assert _span_cost(1000, 2000, u, r) == pytest.approx(1000 * r["cache_write"] / 1e6)
    assert _span_cost(2000, 3000, u, r) == pytest.approx(1000 * r["in"] / 1e6)
    whole = _span_cost(0, 3000, u, r)
    assert whole == pytest.approx(sum(_span_cost(a, a + 1000, u, r) for a in (0, 1000, 2000)))


def test_the_re_read_file_tops_the_waste_table(profile):
    top = profile["waste"][0]
    assert "engine.py" in top["label"]
    assert top["dup_max"] > 1 and top["n"] > top["dup_max"]
    assert top["repeat_cost"] > 0


def test_compaction_shows_up_as_a_prefix_break(profile):
    breaks = [s for s in profile["steps"] if s["broke"]]
    assert len(breaks) == 1
    assert breaks[0]["usage"]["cache_read"] == 0
    assert breaks[0]["broke"]["at"] == 0


def test_unmeasured_system_prompt_is_recovered_as_a_node(profile):
    sysnode = [c for c in profile["tree"]["children"] if c["kind"] == "system"][0]
    assert sysnode["total"]["cost"] > 0.2 * profile["totals"]["cost"]


def test_empty_run_does_not_explode():
    p = analyze([], source="empty")
    assert p["totals"]["calls"] == 0 and p["totals"]["cost"] == 0
