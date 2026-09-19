#!/usr/bin/env python3
"""Assemble the static site (GitHub Pages / Vercel / HF Space) into ./site.

Everything is copied, not bundled: the site serves the same core.css/core.js the
CLI embeds in its reports, so the viewer can never drift from the generator.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agentprof.analyze import analyze            # noqa: E402
from agentprof.ingest import read_auto           # noqa: E402
from agentprof.report import write as write_html  # noqa: E402

SITE = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "site")
DEMO = os.path.join(ROOT, "examples", "demo-session.jsonl")

os.makedirs(SITE, exist_ok=True)
if not os.path.exists(DEMO):
    subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "make_demo.py"), DEMO])

for name in ("core.css", "core.js"):
    shutil.copy(os.path.join(ROOT, "agentprof", "assets", name), os.path.join(SITE, name))
shutil.copy(os.path.join(ROOT, "web", "index.html"), os.path.join(SITE, "index.html"))

profile = analyze(read_auto(DEMO)[1], source="demo-session.jsonl")
with open(os.path.join(SITE, "demo.json"), "w", encoding="utf-8") as fh:
    json.dump(profile, fh, separators=(",", ":"), default=float)
write_html(profile, os.path.join(SITE, "report.html"), title="agentprof demo report")
open(os.path.join(SITE, ".nojekyll"), "w").close()
print("site -> %s" % SITE)
