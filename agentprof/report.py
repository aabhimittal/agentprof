"""Assemble a single self-contained HTML file. No CDN, no fetch, no telemetry."""
import datetime
import json
import os

from . import __version__

ASSETS = os.path.join(os.path.dirname(__file__), "assets")


def asset(name):
    with open(os.path.join(ASSETS, name), "r", encoding="utf-8") as fh:
        return fh.read()


def html(profile, title=None):
    profile = dict(profile)
    meta = dict(profile.get("meta") or {})
    meta["generated"] = datetime.datetime.now().isoformat(timespec="seconds")
    profile["meta"] = meta
    t = profile["totals"]
    sub = "%s &middot; %s &middot; %d model calls &middot; $%.2f &middot; generated %s" % (
        meta.get("source") or "run",
        ", ".join(meta.get("models") or ["?"]),
        t["calls"],
        t["cost"],
        meta["generated"].replace("T", " "),
    )
    data = json.dumps(profile, separators=(",", ":"), default=float)
    out = asset("shell.html")
    for k, v in (
        ("__TITLE__", (title or meta.get("source") or "run") + " - agentprof"),
        ("__CSS__", asset("core.css")),
        ("__JS__", asset("core.js")),
        ("__SUB__", sub),
        ("__VERSION__", "v" + __version__),
        ("__DATA__", data),
    ):
        out = out.replace(k, v)
    return out


def write(profile, path, title=None):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html(profile, title))
    return path
