import copy

from agentprof.analyze import analyze
from agentprof.findings import findings


def _ids(p):
    return [f["id"] for f in p["findings"]]


def test_duplicate_copies_is_the_headline(profile):
    f = profile["findings"][0]
    assert f["id"] == "duplicate-copies" and f["level"] == "high"
    assert "engine.py" in f["detail"] and "6 times in one prompt" in f["detail"]


def test_a_duplicated_block_is_not_also_billed_as_a_resend(profile):
    """The narrower finding wins; the same block must not raise both."""
    dup = [f for f in profile["findings"] if f["id"] == "duplicate-copies"][0]
    resends = [f for f in profile["findings"] if f["id"].startswith("resend-")]
    assert dup["usd"] + sum(f["usd"] for f in resends) <= profile["totals"]["cost"] + 1e-9


def test_no_single_finding_claims_more_than_the_run(profile):
    """Findings may overlap each other, but none may exceed the total spend."""
    for f in profile["findings"]:
        assert f["usd"] <= profile["totals"]["cost"] + 1e-9


def test_prefix_break_is_charged_only_the_recache_premium(profile):
    """Not the whole call - that would double-count the system prefix."""
    brk = [f for f in profile["findings"] if f["id"] == "prefix-break"][0]
    missed = [s for s in profile["steps"] if s["broke"]]
    assert 0 < brk["usd"] < sum(s["cost"] for s in missed)


def test_system_overhead_and_prefix_break_are_reported(profile):
    ids = _ids(profile)
    assert "system-overhead" in ids and "prefix-break" in ids


def test_every_finding_carries_evidence(profile):
    for f in profile["findings"]:
        assert f["title"] and len(f["detail"]) > 40
        assert f["level"] in ("high", "medium", "info")
        assert 0.0 <= f["share"] <= 1.0


def test_clean_run_produces_no_findings():
    totals = {"cost": 1.0, "calls": 10, "hit_rate": 0.95, "out": 5000,
              "billed_in": 100000, "resent_cost": 0.0}
    assert findings(totals, [], [], 0.1, 0.0) == []


def test_low_cache_hit_rate_is_flagged():
    totals = {"cost": 1.0, "calls": 20, "hit_rate": 0.2, "out": 9000,
              "billed_in": 100000, "resent_cost": 0.0}
    out = findings(totals, [], [], 0.0, 0.0)
    assert [f["id"] for f in out] == ["low-cache-hit"]
    assert "20%" in out[0]["title"]


def test_findings_survive_a_profile_round_trip(profile):
    """The report and viewer both consume the serialized form."""
    import json
    again = json.loads(json.dumps(copy.deepcopy(profile), default=float))
    assert _ids(again) == _ids(profile)


def test_empty_run_has_no_findings():
    assert analyze([], source="empty")["findings"] == []
