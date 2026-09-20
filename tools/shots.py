#!/usr/bin/env python3
"""Render the docs images in docs/images/ with headless Chromium.

    python3 tools/shots.py            # uses a bundled Chromium if one is on the box
    CHROME=/path/to/chrome python3 tools/shots.py
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
OUT = os.path.join(ROOT, "docs", "images")
PORT = 8099
CANDIDATES = [
    os.environ.get("CHROME"),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome"),
]

SHOT_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<link rel=stylesheet href="core.css"><style>body{padding:0}.wrap{padding:18px 18px 8px}</style></head>
<body><div class=wrap><main id=app></main></div>
<script src="core.js"></script><script>
var q = new URLSearchParams(location.search);
if (q.get('theme')) document.documentElement.setAttribute('data-theme', q.get('theme'));
var src = q.get('example') ? 'examples/' + q.get('example') + '.json' : 'demo.json';
fetch(src).then(function(r){return r.json();}).then(function(p){
  AgentProf.render(p, document.getElementById('app'));
  var keep = (q.get('panels')||'').split(',').filter(String).map(Number);
  if (keep.length) {
    var panels = [].slice.call(document.querySelectorAll('#app .panel'));
    panels.forEach(function(el,i){ if (keep.indexOf(i)<0) el.remove(); });
    if (q.get('stats') !== '1') { var s=document.querySelector('#app .stats'); if(s) s.remove(); }
    var n=document.querySelector('#app > .note'); if(n && q.get('note')!=='1') n.remove();
  }
  document.title = 'ready';
});
</script></body></html>"""

TERM_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><link rel=stylesheet href="core.css">
<style>body{background:#12110f;padding:22px;margin:0}
pre{font-family:var(--mono);font-size:13px;line-height:1.65;color:#e9e4da;margin:0;
 background:#1b1916;border:1px solid #2e2a25;border-radius:11px;padding:18px 20px;overflow:hidden}
.p{color:#5cc98a}.c{color:#e0b64a}.d{color:#8d877e}.a{color:#ff8c4b}</style></head>
<body><pre><span class=p>$</span> <span class=c>agentprof summary</span>
<span class=d>[agentprof] using ~/.claude/projects/-home-you-engine/3f2a....jsonl</span>
__BODY__</pre></body></html>"""


def chrome():
    for c in CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("no Chromium found; set CHROME=/path/to/chrome")


def serve():
    handler = partial(SimpleHTTPRequestHandler, directory=SITE)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def shoot(binary, url, path, w, h):
    subprocess.check_call([
        binary, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2", "--virtual-time-budget=4000",
        "--window-size=%d,%d" % (w, h), "--screenshot=" + path, url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  %-34s %d KB" % (os.path.basename(path), os.path.getsize(path) / 1024))


def main():
    subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "build_site.py")])
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(SITE, "_shot.html"), "w") as fh:
        fh.write(SHOT_PAGE)
    summary = subprocess.check_output(
        [sys.executable, "-m", "agentprof", "summary", os.path.join(ROOT, "examples", "demo-session.jsonl")],
        cwd=ROOT, stderr=subprocess.DEVNULL).decode()
    body = "\n".join(l for l in summary.splitlines() if not l.startswith("run "))
    body = body.replace("[high]", "<span class=a>[high]</span>").replace("[medium]", "<span class=c>[medium]</span>")
    body = body.replace("&", "&amp;").replace("<", "&lt;")
    for token in ("$0.8099", "39%", "92.7%"):
        body = body.replace(token, "<span class=a>%s</span>" % token)
    with open(os.path.join(SITE, "_term.html"), "w") as fh:
        fh.write(TERM_PAGE.replace("__BODY__", body))

    srv = serve()
    time.sleep(0.4)
    b, base = chrome(), "http://127.0.0.1:%d" % PORT
    print("shots:")
    shoot(b, base + "/index.html", os.path.join(OUT, "hero.png"), 1340, 1420)
    shoot(b, base + "/_shot.html?panels=0&stats=1&example=oss-selfhosted",
          os.path.join(OUT, "unpriced.png"), 1280, 500)
    shoot(b, base + "/_shot.html?panels=0&stats=1", os.path.join(OUT, "findings.png"), 1280, 660)
    shoot(b, base + "/_shot.html?panels=1&theme=dark", os.path.join(OUT, "flamegraph.png"), 1280, 340)
    shoot(b, base + "/_shot.html?panels=2", os.path.join(OUT, "cache.png"), 1280, 400)
    shoot(b, base + "/_shot.html?panels=3&theme=dark", os.path.join(OUT, "waste.png"), 1280, 470)
    shoot(b, base + "/_term.html", os.path.join(OUT, "terminal.png"), 980, 620)
    srv.shutdown()
    for tmp in ("_shot.html", "_term.html"):
        os.remove(os.path.join(SITE, tmp))


if __name__ == "__main__":
    main()
