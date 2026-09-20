import json

import pytest

from agentprof import pricing
from agentprof.analyze import analyze
from agentprof.ingest import read_auto


@pytest.fixture(autouse=True)
def restore_table():
    saved, unpriced = dict(pricing.MODELS), set(pricing.UNPRICED)
    yield
    pricing.MODELS.clear(), pricing.MODELS.update(saved)
    pricing.UNPRICED.clear(), pricing.UNPRICED.update(unpriced)


def test_known_models_keep_their_published_rates():
    r = pricing.rates("claude-opus-5")
    assert (r["in"], r["out"], r["priced"]) == (5.0, 25.0, True)
    assert r["cache_read"] == 0.5 and r["cache_write"] == 6.25


def test_unknown_models_are_unpriced_not_guessed():
    r = pricing.rates("meta-llama/Llama-3.3-70B-Instruct")
    assert r["priced"] is False and r["in"] == 0.0 and r["out"] == 0.0
    assert pricing.cost("meta-llama/Llama-3.3-70B-Instruct",
                        {"input": 10_000_000, "output": 1_000_000}) == 0.0
    assert "meta-llama/Llama-3.3-70B-Instruct" in pricing.UNPRICED


def test_overrides_price_your_own_endpoint(tmp_path):
    f = tmp_path / "prices.json"
    f.write_text(json.dumps({"models": {"meta-llama/Llama-3.3-70B-Instruct": {"in": 0.6, "out": 0.6}}}))
    added = pricing.load_overrides(str(f))
    assert added == ["meta-llama/Llama-3.3-70B-Instruct"]
    r = pricing.rates("meta-llama/Llama-3.3-70B-Instruct")
    assert r["priced"] and r["in"] == 0.6
    assert pricing.cost("meta-llama/Llama-3.3-70B-Instruct", {"input": 1_000_000}) == pytest.approx(0.6)


def test_a_malformed_pricing_file_is_rejected_loudly(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"models": {"x": {"input": 1}}}))
    with pytest.raises(ValueError):
        pricing.load_overrides(str(f))


def test_unpriced_runs_report_tokens_and_still_find_problems(tmp_path):
    from agentprof.examples import oss_selfhosted

    p = tmp_path / "oss.jsonl"
    p.write_text("\n".join(oss_selfhosted()) + "\n")
    prof = analyze(read_auto(str(p))[1], source="oss.jsonl")

    assert prof["totals"]["priced"] is False
    assert prof["totals"]["cost"] == 0.0
    assert prof["totals"]["billed_in"] > 0
    assert prof["meta"]["unpriced"] == ["meta-llama/Llama-3.3-70B-Instruct"]
    assert prof["findings"], "token-based findings must still fire without prices"
    assert prof["waste"][0]["repeat_tok"] > 0


def test_pricing_the_same_run_turns_the_tokens_into_dollars(tmp_path):
    from agentprof.examples import oss_selfhosted

    f = tmp_path / "prices.json"
    f.write_text(json.dumps({"models": {"meta-llama/Llama-3.3-70B-Instruct": {"in": 0.6, "out": 0.6}}}))
    p = tmp_path / "oss.jsonl"
    p.write_text("\n".join(oss_selfhosted()) + "\n")

    before = analyze(read_auto(str(p))[1], source="oss.jsonl")
    pricing.load_overrides(str(f))
    after = analyze(read_auto(str(p))[1], source="oss.jsonl")

    assert before["totals"]["cost"] == 0.0 and after["totals"]["cost"] > 0.0
    assert after["totals"]["billed_in"] == before["totals"]["billed_in"]
    assert after["totals"]["priced"] is True
