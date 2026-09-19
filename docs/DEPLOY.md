# Deploying the viewer

The site is static: `python3 tools/build_site.py` writes `site/` (index.html, core.js, core.css,
demo.json, report.html). Every target below serves that directory. Each needs one manual step the
repo cannot do for you.

## GitHub Pages — `https://aabhimittal.github.io/agentprof/`

1. Merge this branch to `main`.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.** (Required once; the
   workflow cannot enable Pages on its own.)
3. `.github/workflows/pages.yml` then builds and deploys on every push to `main`, and can be
   re-run by hand from the Actions tab.

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
