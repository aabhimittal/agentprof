"""agentprof command line."""
import argparse
import json
import os
import sys
import webbrowser

from . import __version__
from .analyze import analyze
from .ingest import claude_code, read_auto
from .report import write as write_report

HELP = """examples:
  agentprof report                     profile the newest Claude Code session for this directory
  agentprof report session.jsonl       profile a specific transcript
  agentprof summary                    same numbers, in the terminal
  agentprof proxy --out run.ndjson     record any agent that talks to the Messages API
  agentprof export -o profile.json     normalized profile for the web viewer
  agentprof compare old.json new.json  did the change actually get cheaper?
"""


def _resolve(path):
    if path:
        return path
    found = claude_code.find_sessions()
    if not found:
        sys.exit("no log given and no Claude Code transcript found under ~/.claude/projects")
    sys.stderr.write("[agentprof] using %s\n" % found[0])
    return found[0]


def _profile(path):
    """Accept either a raw log or a profile already exported with `agentprof export`."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        head = fh.read(400).lstrip()
    if head.startswith("{") and '"totals"' in head:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    fmt, events = read_auto(path)
    if not events:
        sys.exit("no model calls found in %s" % path)
    return analyze(events, source=os.path.basename(path))


def cmd_report(a):
    prof = _profile(_resolve(a.log))
    out = a.out or "agentprof-report.html"
    write_report(prof, out)
    size = os.path.getsize(out) / 1024.0
    print("%s  (%.0f KB, %d calls, $%.2f)" % (out, size, prof["totals"]["calls"], prof["totals"]["cost"]))
    if a.open:
        webbrowser.open("file://" + os.path.abspath(out))


def cmd_export(a):
    prof = _profile(_resolve(a.log))
    out = a.out or "agentprof.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(prof, fh, separators=(",", ":"), default=float)
    print(out)


def cmd_summary(a):
    p = _profile(_resolve(a.log))
    t, m = p["totals"], p["meta"]
    print("run        %s  (%s)" % (m["source"], ", ".join(m["models"])))
    print("cost       $%.4f over %d model calls / %d tool calls" % (t["cost"], t["calls"], t["tools"]))
    print("tokens     %d billed input (%d cached, %d written, %d fresh), %d output"
          % (t["billed_in"], t["cache_read"], t["cache_write"], t["in"], t["out"]))
    print("cache      %.1f%% hit rate, %d prefix break(s)"
          % (100 * t["hit_rate"], sum(1 for s in p["steps"] if s["broke"])))
    print("re-sends   $%.4f (%.0f%% of spend) billed on content already sent once"
          % (t["resent_cost"], 100 * t["resent_share"]))
    if p.get("findings"):
        print("\nfindings:")
        for f in p["findings"][:5]:
            head = "  [%s] %s" % (f["level"], f["title"])
            print(head + ("  ($%.4f, %.0f%% of run)" % (f["usd"], 100 * f["share"]) if f["usd"] else ""))
    print("\ntop context blocks by re-send cost:")
    for w in p["waste"][:10]:
        print("  $%-8.4f %-42s %2d copies x %3d billings  %6.1f KB"
              % (w["repeat_cost"], w["label"][:42], w["dup_max"], w["n"], w["bytes"] / 1024.0))


def _delta(name, a, b, fmt="%s", pct=False):
    d = b - a
    sign = "+" if d >= 0 else "-"
    if pct:
        return "%-16s %12s %12s %12s" % (name, "%.1f%%" % (100 * a), "%.1f%%" % (100 * b),
                                         "%s%.1fpt" % (sign, abs(100 * d)))
    return "%-16s %12s %12s %12s" % (name, fmt % a, fmt % b, sign + (fmt % abs(d)).lstrip("$+"))


def cmd_compare(a):
    before, after = _profile(a.before), _profile(a.after)
    tb, ta = before["totals"], after["totals"]
    print("%-16s %12s %12s %12s" % ("", "before", "after", "delta"))
    print(_delta("cost", tb["cost"], ta["cost"], "$%.4f"))
    print(_delta("billed input", tb["billed_in"], ta["billed_in"], "%d"))
    print(_delta("output", tb["out"], ta["out"], "%d"))
    print(_delta("model calls", tb["calls"], ta["calls"], "%d"))
    print(_delta("cache hit rate", tb["hit_rate"], ta["hit_rate"], pct=True))
    print(_delta("re-sent share", tb["resent_share"], ta["resent_share"], pct=True))
    if tb["cost"]:
        print("\n%+.1f%% total cost" % (100 * (ta["cost"] - tb["cost"]) / tb["cost"]))

    lb, la = before.get("labels", {}), after.get("labels", {})
    moves = []
    for label in set(list(lb) + list(la)):
        d = la.get(label, 0.0) - lb.get(label, 0.0)
        if abs(d) > 0.0005:
            moves.append((d, label))
    if moves:
        moves.sort(key=lambda m: -abs(m[0]))
        print("\nbiggest movers by attributed cost:")
        for d, label in moves[:10]:
            print("  %s$%-8.4f %s" % ("+" if d > 0 else "-", abs(d), label[:56]))


def cmd_proxy(a):
    from .proxy import serve
    serve(a.out, a.host, a.port, not a.quiet)


def cmd_demo(a):
    import tempfile

    from .demo import lines
    tmp = os.path.join(tempfile.mkdtemp(prefix="agentprof-demo-"), "demo-session.jsonl")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines()) + "\n")
    prof = analyze(read_auto(tmp)[1], source="demo-session.jsonl")
    out = a.out or "agentprof-demo.html"
    write_report(prof, out, title="agentprof demo")
    print(out)
    if a.open:
        webbrowser.open("file://" + os.path.abspath(out))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="agentprof", description="Flamegraph profiler for agent token spend.",
        epilog=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version="agentprof " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    def add(name, fn, log=True):
        p = sub.add_parser(name)
        if log:
            p.add_argument("log", nargs="?", help="transcript or NDJSON capture (default: newest Claude Code session)")
        p.set_defaults(fn=fn)
        return p

    p = add("report", cmd_report)
    p.add_argument("-o", "--out", help="output HTML file")
    p.add_argument("--open", action="store_true", help="open the report in a browser")
    p = add("export", cmd_export)
    p.add_argument("-o", "--out", help="output JSON file")
    add("summary", cmd_summary)
    p = sub.add_parser("compare")
    p.add_argument("before", help="log or exported profile from before the change")
    p.add_argument("after", help="log or exported profile from after the change")
    p.set_defaults(fn=cmd_compare)
    p = add("proxy", cmd_proxy, log=False)
    p.add_argument("-o", "--out", default="agentprof-run.ndjson")
    p.add_argument("--port", type=int, default=8788)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("-q", "--quiet", action="store_true")
    p = add("demo", cmd_demo, log=False)
    p.add_argument("-o", "--out")
    p.add_argument("--open", action="store_true")

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 1
    try:
        a.fn(a)
    except BrokenPipeError:
        # `agentprof summary | head` closes the pipe early. Point stdout at
        # /dev/null so the interpreter's exit-time flush has somewhere to go,
        # and leave quietly instead of printing a traceback at the user.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
