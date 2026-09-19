---
title: agentprof
emoji: 🔥
colorFrom: orange
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Flamegraph profiler for agent token spend - local only
---

# agentprof

Flamegraph profiler for agent token spend. This Space is the static viewer: it renders a demo
profile, and anything you drop into it is parsed in your browser — nothing is uploaded.

Generate your own profile locally:

```bash
pipx run agentprof report --open      # newest Claude Code session
agentprof export -o agentprof.json    # then drop that file into this page
```

Source and docs: https://github.com/aabhimittal/agentprof
