#!/usr/bin/env python3
"""Assemble the static site (GitHub Pages / Vercel / HF Space) into ./site.

Everything is copied, not bundled: the site serves the same core.css/core.js the
CLI embeds in its reports, so the viewer can never drift from the generator.
Example profiles are generated here from agentprof/examples.py, which means the
gallery is reproducible from source rather than a pile of committed JSON.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentprof.analyze import analyze            # noqa: E402
from agentprof.demo import lines as demo_lines   # noqa: E402
from agentprof.examples import EXAMPLES          # noqa: E402
from agentprof.ingest import read_auto           # noqa: E402
from agentprof.report import write as write_html  # noqa: E402

SITE = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "site")
EXDIR = os.path.join(SITE, "examples")


def profile_of(lines, source):
    tmp = os.path.join(tempfile.mkdtemp(prefix="agentprof-site-"), source)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    fmt, events = read_auto(tmp)
    os.remove(tmp)
    return fmt, analyze(events, source=source)


def main():
    os.makedirs(EXDIR, exist_ok=True)
    for name in ("core.css", "core.js"):
        shutil.copy(os.path.join(ROOT, "agentprof", "assets", name), os.path.join(SITE, name))
    shutil.copy(os.path.join(ROOT, "web", "index.html"), os.path.join(SITE, "index.html"))
    open(os.path.join(SITE, ".nojekyll"), "w").close()

    gallery = [("coding-agent", "Coding agent fixing a test",
                "A Claude Code session: nine re-reads of the same 8.6 KB file, a subagent, and an "
                "auto-compaction that throws the prefix cache away.",
                demo_lines, "claude-code")]
    gallery += [(name, title, blurb, fn, fmt) for name, (title, blurb, fn, fmt) in EXAMPLES.items()]

    manifest = []
    for name, title, blurb, fn, expect_fmt in gallery:
        fmt, prof = profile_of(fn(), name + ".jsonl")
        assert fmt == expect_fmt, "%s parsed as %s, expected %s" % (name, fmt, expect_fmt)
        with open(os.path.join(EXDIR, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(prof, fh, separators=(",", ":"), default=float)
        t = prof["totals"]
        manifest.append({
            "id": name, "title": title, "blurb": blurb, "format": fmt,
            "models": prof["meta"]["models"], "priced": t["priced"],
            "cost": t["cost"], "calls": t["calls"], "billed_in": t["billed_in"],
            "hit_rate": t["hit_rate"], "findings": len(prof["findings"]),
        })
        if name == "coding-agent":
            with open(os.path.join(SITE, "demo.json"), "w", encoding="utf-8") as fh:
                json.dump(prof, fh, separators=(",", ":"), default=float)
            write_html(prof, os.path.join(SITE, "report.html"), title="agentprof demo report")

    with open(os.path.join(EXDIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"examples": manifest}, fh, indent=1, default=float)
    print("site -> %s (%d examples)" % (SITE, len(manifest)))


if __name__ == "__main__":
    main()
