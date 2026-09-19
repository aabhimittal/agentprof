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
    print("\ntop context blocks by re-send cost:")
    for w in p["waste"][:10]:
        print("  $%-8.4f %-42s %2d copies x %3d billings  %6.1f KB"
              % (w["repeat_cost"], w["label"][:42], w["dup_max"], w["n"], w["bytes"] / 1024.0))


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
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
