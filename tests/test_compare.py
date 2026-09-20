import json

from agentprof.cli import main


def test_compare_reports_deltas_and_movers(profile, tmp_path, capsys):
    a = tmp_path / "before.json"
    b = tmp_path / "after.json"
    a.write_text(json.dumps(profile, default=float))

    cheaper = json.loads(json.dumps(profile, default=float))
    cheaper["totals"]["cost"] = profile["totals"]["cost"] / 2.0
    cheaper["totals"]["hit_rate"] = 0.99
    cheaper["labels"] = dict(profile["labels"])
    top = max(cheaper["labels"], key=lambda k: cheaper["labels"][k])
    cheaper["labels"][top] = 0.0
    b.write_text(json.dumps(cheaper, default=float))

    main(["compare", str(a), str(b)])
    out = capsys.readouterr().out
    assert "before" in out and "after" in out and "delta" in out
    assert "-50.0%" in out or "-50%" in out
    assert "biggest movers" in out and top[:20] in out


def test_profile_loader_accepts_exported_json(profile, tmp_path):
    from agentprof.cli import _profile
    p = tmp_path / "agentprof.json"
    p.write_text(json.dumps(profile, default=float))
    assert _profile(str(p))["totals"]["calls"] == profile["totals"]["calls"]




def test_summary_exits_quietly_when_the_pipe_closes(demo_path, monkeypatch):
    """`agentprof summary | head` must not raise a traceback at the user."""
    import io

    class ClosedPipe(io.StringIO):
        def write(self, _s):
            raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("sys.stdout", ClosedPipe())
    assert main(["summary", demo_path]) == 0
