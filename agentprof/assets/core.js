/* agentprof viewer - no dependencies, no network. Renders a profile object. */
(function (global) {
  "use strict";

  var METRICS = {
    cost: { label: "cost", fmt: usd, unit: "$" },
    tok: { label: "tokens", fmt: tokens, unit: "tok" },
    ms: { label: "time", fmt: ms, unit: "s" }
  };
  var HUE = { root: [30, 6], system: [262, 42], llm: [210, 52], tool: [26, 62] };

  function usd(v) { return v >= 1 ? "$" + v.toFixed(2) : "$" + v.toFixed(v < 0.01 ? 4 : 3); }
  function tokens(v) {
    if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + "k";
    return String(Math.round(v));
  }
  function ms(v) { return v >= 60000 ? (v / 60000).toFixed(1) + "m" : v >= 1000 ? (v / 1000).toFixed(1) + "s" : Math.round(v) + "ms"; }
  function kb(b) { return b >= 1024 ? (b / 1024).toFixed(1) + " KB" : b + " B"; }
  function pct(v) { return (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%"; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }
  function el(tag, cls, html) { var n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; }
  function hash(s) { var h = 0, i; for (i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; } return Math.abs(h); }
  function isDark() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return !!(global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function color(node) {
    var h = HUE[node.kind] || HUE.tool, dark = isDark();
    var jitter = (hash(node.name) % 13) - 6;
    var l = dark ? 42 + jitter * 0.7 : 52 + jitter * 0.8;
    return "hsl(" + (h[0] + jitter) + "," + h[1] + "%," + l + "%)";
  }

  function render(profile, host) {
    host.innerHTML = "";
    var t = profile.totals, m = profile.meta || {};
    host.appendChild(statRow(t, m));
    host.appendChild(flamePanel(profile));
    host.appendChild(cachePanel(profile));
    host.appendChild(wastePanel(profile));
    host.appendChild(el("p", "note",
      "Token counts per context block are estimated at ~4 bytes/token; usage totals and prices are exact. " +
      "Cost is attributed by prompt position: the first <code>cache_read</code> tokens of each request bill at the cache rate, " +
      "the next <code>cache_creation</code> tokens at the write rate, the remainder at full input price."));
  }

  function statRow(t, m) {
    var g = el("div", "stats");
    function stat(k, v, n) { var s = el("div", "stat"); s.appendChild(el("div", "k", esc(k))); s.appendChild(el("div", "v", v)); if (n) s.appendChild(el("div", "n", n)); return s; }
    g.appendChild(stat("run cost", usd(t.cost), t.calls + " model calls, " + (t.tools || 0) + " tool calls"));
    g.appendChild(stat("billed input", tokens(t.billed_in), tokens(t.out) + " output tokens"));
    g.appendChild(stat("cache hit rate", pct(t.hit_rate), tokens(t.cache_write) + " written, " + tokens(t.cache_read) + " read"));
    g.appendChild(stat("spent on re-sends", pct(t.resent_share), usd(t.resent_cost) + " billed more than once"));
    g.appendChild(stat("wall time", ms((m.duration_s || 0) * 1000), (m.models || []).join(", ")));
    return g;
  }

  /* ---------- flamegraph ---------- */
  function flamePanel(profile) {
    var panel = el("div", "panel"), metric = "cost", zoom = profile.tree, q = "";
    var head = el("div", "panel-head");
    var title = el("div", "", "<h2>Attribution flamegraph</h2><div class='sub'>width = what the run spent <em>because of</em> that node, including every later re-send</div>");
    var ctl = el("div", "controls");
    Object.keys(METRICS).forEach(function (k) {
      var b = el("button", "btn", METRICS[k].label);
      b.setAttribute("aria-pressed", String(k === metric));
      b.onclick = function () {
        metric = k;
        [].forEach.call(ctl.querySelectorAll("button"), function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        draw();
      };
      ctl.appendChild(b);
    });
    var search = el("input");
    search.type = "search"; search.placeholder = "highlight (e.g. engine.py)";
    search.oninput = function () { q = search.value.trim().toLowerCase(); draw(); };
    ctl.appendChild(search);
    head.appendChild(title); head.appendChild(ctl);
    panel.appendChild(head);

    var crumb = el("div", "crumb");
    var flame = el("div", "flame");
    panel.appendChild(crumb); panel.appendChild(flame);
    var legend = el("div", "legend");
    [["system", "system + tool definitions"], ["llm", "model call (its own output)"], ["tool", "tool call / injected context"]].forEach(function (p) {
      legend.appendChild(el("span", "", "<i style='background:" + color({ kind: p[0], name: p[0] }) + "'></i>" + p[1]));
    });
    panel.appendChild(legend);

    var tip = el("div", "tip"); tip.style.display = "none"; document.body.appendChild(tip);

    function path(node, target, acc) {
      acc = acc || [];
      if (node === target) return acc.concat([node]);
      for (var i = 0; i < node.children.length; i++) {
        var r = path(node.children[i], target, acc.concat([node]));
        if (r) return r;
      }
      return null;
    }

    function draw() {
      var W = flame.clientWidth || 900, rows = [];
      var total = zoom.total[metric] || 1;
      (function lay(n, depth, x, w) {
        rows.push({ n: n, d: depth, x: x, w: w });
        var off = x;
        for (var i = 0; i < n.children.length; i++) {
          var c = n.children[i], cw = (c.total[metric] / total) * W;
          if (cw >= 0.6) lay(c, depth + 1, off, cw);
          off += cw;
        }
      })(zoom, 0, 0, W);

      var maxd = 0;
      rows.forEach(function (r) { maxd = Math.max(maxd, r.d); });
      flame.style.height = (maxd + 1) * 21 + 4 + "px";
      flame.innerHTML = "";
      rows.forEach(function (r) {
        var d = el("div", "fr");
        d.style.left = r.x + "px"; d.style.width = Math.max(1, r.w - 1) + "px";
        d.style.top = r.d * 21 + "px"; d.style.background = color(r.n);
        var share = r.n.total[metric] / (profile.tree.total[metric] || 1);
        if (r.w > 42) d.textContent = r.n.name + " (" + METRICS[metric].fmt(r.n.total[metric]) + ")";
        if (q) { if (r.n.name.toLowerCase().indexOf(q) >= 0) d.classList.add("hit"); else d.classList.add("dim"); }
        d.onmousemove = function (ev) {
          tip.style.display = "block";
          tip.style.left = Math.min(ev.clientX + 14, global.innerWidth - 392) + "px";
          tip.style.top = Math.min(ev.clientY + 16, global.innerHeight - 150) + "px";
          var mt = r.n.meta || {};
          tip.innerHTML = "<b>" + esc(r.n.name) + "</b><br>" +
            "<span class='row'>" + esc(r.n.kind) + (mt.model ? " &middot; " + esc(mt.model) : "") + "</span><br>" +
            "<span class='row'>total " + METRICS[metric].fmt(r.n.total[metric]) + " &middot; " + pct(share) + " of run</span><br>" +
            "<span class='row'>self " + METRICS[metric].fmt(r.n.self[metric]) + " &middot; " + r.n.children.length + " children</span>" +
            (mt.billed ? "<br><span class='row'>billed " + mt.billed + "x, up to " + mt.copies + " copies in one request, " + kb(mt.bytes) + " each</span>" : "");
        };
        d.onmouseleave = function () { tip.style.display = "none"; };
        d.onclick = function () { zoom = r.n; tip.style.display = "none"; draw(); };
        flame.appendChild(d);
      });

      var p = path(profile.tree, zoom) || [zoom];
      crumb.innerHTML = "";
      p.forEach(function (n, i) {
        if (i) crumb.appendChild(document.createTextNode(" / "));
        var a = el("a", "", esc(n.name));
        a.onclick = function () { zoom = n; draw(); };
        crumb.appendChild(a);
      });
      if (zoom !== profile.tree) crumb.appendChild(document.createTextNode("  (click a frame to zoom)"));
    }

    setTimeout(draw, 0);
    global.addEventListener("resize", debounce(draw, 120));
    panel.__redraw = draw;
    return panel;
  }

  function debounce(fn, n) { var t; return function () { clearTimeout(t); t = setTimeout(fn, n); }; }

  /* ---------- cache ---------- */
  function cachePanel(profile) {
    var panel = el("div", "panel");
    var breaks = profile.steps.filter(function (s) { return s.broke; });
    panel.appendChild(el("div", "panel-head",
      "<div><h2>Prefix cache, call by call</h2><div class='sub'>green = read from cache, amber = written to cache, orange = billed at full input price</div></div>" +
      "<span class='pill'>" + breaks.length + " prefix break" + (breaks.length === 1 ? "" : "s") + "</span>"));
    var chart = el("div", "cachechart");
    var max = 1;
    profile.steps.forEach(function (s) { max = Math.max(max, s.usage.input + s.usage.cache_read + s.usage.cache_write); });
    var tip = el("div", "tip"); tip.style.display = "none"; document.body.appendChild(tip);
    profile.steps.forEach(function (s, i) {
      var b = el("div", "cb" + (s.broke ? " break" : ""));
      var h = 116 / max;
      b.appendChild(el("span", "i")).style.height = (s.usage.input * h) + "px";
      b.appendChild(el("span", "w")).style.height = (s.usage.cache_write * h) + "px";
      b.appendChild(el("span", "r")).style.height = (s.usage.cache_read * h) + "px";
      b.onmousemove = function (ev) {
        tip.style.display = "block";
        tip.style.left = Math.min(ev.clientX + 14, global.innerWidth - 392) + "px";
        tip.style.top = Math.max(12, ev.clientY - 130) + "px";
        tip.innerHTML = "<b>" + esc(s.label || ("call " + (i + 1))) + "</b><br>" +
          "<span class='row'>" + usd(s.cost) + " &middot; " + ms(s.ms) + " &middot; hit " + pct(s.hit) + "</span><br>" +
          "<span class='row'>cache read " + tokens(s.usage.cache_read) + " &middot; written " + tokens(s.usage.cache_write) +
          " &middot; fresh " + tokens(s.usage.input) + "</span><br>" +
          "<span class='row'>output " + tokens(s.usage.output) + " &middot; " + s.blocks + " context blocks</span>" +
          (s.broke ? "<br><span class='row' style='color:var(--accent)'>prefix broke at block " + s.broke.at + " of " +
            s.broke.of + " &mdash; " + esc(s.broke.label) + " (" + esc(s.broke.kind) + ")</span>" : "");
      };
      b.onmouseleave = function () { tip.style.display = "none"; };
      chart.appendChild(b);
    });
    panel.appendChild(chart);
    if (breaks.length) {
      var ul = el("div", "note", "<b>Invalidations</b>");
      var tbl = el("table");
      tbl.innerHTML = "<tr><th>call</th><th>broke at</th><th>first changed block</th><th class='num'>re-cached</th><th class='num'>cost of the miss</th></tr>";
      breaks.forEach(function (s) {
        var row = el("tr");
        row.innerHTML = "<td class='name'>" + esc(s.label) + "</td><td class='num'>block " + s.broke.at + " / " + s.broke.of + "</td>" +
          "<td class='name'>" + esc(s.broke.label) + "</td><td class='num'>" + tokens(s.usage.cache_write) + "</td>" +
          "<td class='num'>" + usd(s.cost) + "</td>";
        tbl.appendChild(row);
      });
      panel.appendChild(ul); panel.appendChild(tbl);
    }
    return panel;
  }

  /* ---------- waste ---------- */
  function wastePanel(profile) {
    var panel = el("div", "panel"), mode = "waste";
    var head = el("div", "panel-head");
    head.appendChild(el("div", "", "<h2>Waste attribution</h2><div class='sub'>context blocks ranked by what their repeat billing cost</div>"));
    var ctl = el("div", "controls");
    [["waste", "re-sent"], ["top_cost", "most expensive"]].forEach(function (p) {
      var b = el("button", "btn", p[1]);
      b.setAttribute("aria-pressed", String(p[0] === mode));
      b.onclick = function () {
        mode = p[0];
        [].forEach.call(ctl.querySelectorAll("button"), function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        fill();
      };
      ctl.appendChild(b);
    });
    head.appendChild(ctl);
    panel.appendChild(head);
    var tbl = el("table");
    panel.appendChild(tbl);
    function fill() {
      var rows = profile[mode] || [];
      tbl.innerHTML = "<tr><th>context block</th><th>type</th><th class='num'>copies in one request</th>" +
        "<th class='num'>times billed</th><th class='num'>size</th><th class='num'>" +
        (mode === "waste" ? "cost of re-sends" : "total cost") + "</th><th class='num'>% of run</th></tr>";
      rows.forEach(function (w) {
        var c = mode === "waste" ? w.repeat_cost : w.cost;
        var r = el("tr");
        r.innerHTML = "<td class='name' title='" + esc(w.label) + "'>" + esc(w.label) + "</td>" +
          "<td><span class='pill'>" + esc(w.kind) + "</span></td>" +
          "<td class='num'>" + (w.dup_max > 1 ? "<b>" + w.dup_max + "</b>" : w.dup_max) + "</td>" +
          "<td class='num'>" + w.n + "</td><td class='num'>" + kb(w.bytes) + "</td>" +
          "<td class='num'>" + usd(c) + "</td>" +
          "<td class='num'>" + pct(c / (profile.totals.cost || 1)) + "</td>";
        tbl.appendChild(r);
      });
      if (!rows.length) tbl.innerHTML = "<tr><td class='sub'>nothing re-sent more than once.</td></tr>";
    }
    fill();
    return panel;
  }

  function theme(next) {
    var t = next || (isDark() ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("agentprof-theme", t); } catch (e) {}
    return t;
  }
  function restoreTheme() {
    try { var t = localStorage.getItem("agentprof-theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch (e) {}
  }

  global.AgentProf = { render: render, theme: theme, restoreTheme: restoreTheme, fmt: { usd: usd, tokens: tokens, ms: ms, kb: kb, pct: pct } };
})(window);
