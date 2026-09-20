# Deploying the viewer

The site is static: `python3 tools/build_site.py` writes `site/` (index.html, core.js, core.css,
demo.json, report.html). Every target below serves that directory. Each needs one manual step the
repo cannot do for you.

## GitHub Pages — `https://aabhimittal.github.io/agentprof/`

`.github/workflows/pages.yml` builds and deploys on every push to `main`, and can be re-run by hand
from the Actions tab.

**One setting is needed first.** The workflow passes `enablement: true` to `actions/configure-pages`,
which tries to create the Pages site for you, but `GITHUB_TOKEN` is usually not allowed to do that:

```
Get Pages site failed. Error: Not Found
Create Pages site failed. Error: Resource not accessible by integration
```

Either fix works, both are one click:

- **Settings → Pages → Build and deployment → Source: GitHub Actions.** The site then exists and the
  workflow stops trying to create it. This is the reliable option.
- **Settings → Actions → General → Workflow permissions → Read and write permissions.** This raises
  the ceiling on what the workflow's token may request, which can let `enablement: true` succeed.

Then re-run the failed `pages` run from the Actions tab (or push to `main`); the deploy itself needs
no further changes.

## Vercel — `https://agentprof.vercel.app`

1. vercel.com → **Add New → Project → Import** `aabhimittal/agentprof`.
2. Accept the defaults: `vercel.json` already sets the build command
   (`python3 tools/build_site.py`) and output directory (`site`). No environment variables, no
   install step — the project has no dependencies.
3. Optional: set the production domain to `agentprof.vercel.app` under Settings → Domains.

Nothing in the build touches the network, so the Vercel build works on the free tier with the
default Python-capable image.

## Hugging Face Space — `https://huggingface.co/spaces/<you>/agentprof`

Either push from CI or once by hand.

**From CI:** add a write-scoped token as the repository secret `HF_TOKEN`
(Settings → Secrets and variables → Actions). Optionally set the repository variable `HF_SPACE` to
`owner/name` if it is not `abhimittal/agentprof`. `.github/workflows/hf-space.yml` creates the
Space if it is missing and uploads `site/` on every push to `main`; without the secret it skips.

**By hand:**

```bash
pip install huggingface_hub
python3 tools/build_site.py
cp web/space-README.md site/README.md      # the Space card: sdk: static, app_file: index.html
huggingface-cli upload <you>/agentprof site . --repo-type=space
```

## Checking a build before you ship it

```bash
python3 tools/build_site.py
python3 -m http.server -d site 8000        # http://localhost:8000
```

`demo.json` is fetched at load, so the page needs to be served over HTTP — opening `site/index.html`
straight off the filesystem will show the demo-load error. A CLI-generated report
(`agentprof report`) has no such restriction: it is one file with everything inlined.
