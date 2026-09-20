"""Model pricing.

The shipped table is Anthropic's published rates (assets/pricing.json, shared
with the JS viewer). Everything else - self-hosted vLLM, Ollama, an OpenRouter
or Together endpoint - is priced by whatever the user tells us, because
inventing a number for someone else's endpoint produces confident nonsense.

A model with no known price is reported as *unpriced*: token counts stay exact
and every cost is zero, which is visible rather than misleading. Supply rates
with `--pricing FILE` (same shape as assets/pricing.json, merged over it).
"""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "assets", "pricing.json")

with open(_PATH, "r", encoding="utf-8") as _fh:
    TABLE = json.load(_fh)

MODELS = dict(TABLE["models"])
CR_MULT = TABLE["default_cache_read_multiplier"]
CW_MULT = TABLE["default_cache_write_multiplier"]
UNPRICED = set()


def load_overrides(path):
    """Merge a user pricing file over the built-in table. Returns the added ids."""
    with open(path, "r", encoding="utf-8") as fh:
        user = json.load(fh)
    models = user.get("models", user)
    if not isinstance(models, dict):
        raise ValueError("%s: expected {\"models\": {id: {in, out, ...}}}" % path)
    for mid, spec in models.items():
        if not isinstance(spec, dict) or "in" not in spec or "out" not in spec:
            raise ValueError("%s: model %r needs at least 'in' and 'out' (USD per 1M tokens)" % (path, mid))
    MODELS.update(models)
    UNPRICED.difference_update(models)
    return sorted(models)


def _lookup(model):
    m = MODELS.get(model)
    if m is not None:
        return m
    best = None
    for key in MODELS:
        if model and key != "self-hosted" and (model.startswith(key) or key in model):
            if best is None or len(key) > len(best):
                best = key
    if best:
        return MODELS[best]
    if model:
        UNPRICED.add(model)
    return None


def rates(model):
    """USD per 1M tokens: {in, out, cache_read, cache_write, priced}."""
    m = _lookup(model)
    if m is None:
        return {"in": 0.0, "out": 0.0, "cache_read": 0.0, "cache_write": 0.0, "priced": False}
    return {
        "in": m["in"],
        "out": m["out"],
        "cache_read": m.get("cache_read", m["in"] * CR_MULT),
        "cache_write": m.get("cache_write", m["in"] * CW_MULT),
        "priced": True,
    }


def cost(model, usage):
    """USD cost of one call. usage keys: input, output, cache_read, cache_write."""
    r = rates(model)
    return (
        usage.get("input", 0) * r["in"]
        + usage.get("output", 0) * r["out"]
        + usage.get("cache_read", 0) * r["cache_read"]
        + usage.get("cache_write", 0) * r["cache_write"]
    ) / 1_000_000.0
