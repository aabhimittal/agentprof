#!/usr/bin/env python3
"""Write the bundled synthetic demo transcript to disk (default: examples/demo-session.jsonl)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentprof.demo import lines  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "examples/demo-session.jsonl"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
rows = lines()
with open(out, "w", encoding="utf-8") as fh:
    fh.write("\n".join(rows) + "\n")
print("wrote %s (%d entries)" % (out, len(rows)))
