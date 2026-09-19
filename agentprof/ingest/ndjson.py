"""Reader for agentprof's own NDJSON capture format (written by `agentprof proxy`).

One JSON object per line, already in normalized Event shape.
"""
import json


def sniff(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                return None
            if obj.get("kind") in ("llm", "tool"):
                return "ndjson"
            return None
    return None


def read(path):
    events = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("kind") in ("llm", "tool"):
                events.append(obj)
    return events
