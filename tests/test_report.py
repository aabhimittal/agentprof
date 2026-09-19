import json
import re

from agentprof.report import html


def test_report_is_self_contained(profile):
    page = html(profile, title="t")
    assert "<script src=" not in page and "<link rel=\"stylesheet\"" not in page
    assert not re.search(r'(src|href)\s*=\s*"https?://[^"]+"', page.replace('href="https://github.com/aabhimittal/agentprof"', ""))
    assert "AgentProf.render" in page and "__DATA__" not in page


def test_report_embeds_a_parseable_profile(profile):
    page = html(profile)
    blob = page.split("window.AGENTPROF_PROFILE = ", 1)[1].split(";</script>", 1)[0]
    parsed = json.loads(blob)
    assert parsed["totals"]["calls"] == profile["totals"]["calls"]
    assert parsed["tree"]["children"]
