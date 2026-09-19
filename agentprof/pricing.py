"""Model pricing. Single source of truth is assets/pricing.json (shared with the JS viewer)."""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "assets", "pricing.json")

with open(_PATH, "r", encoding="utf-8") as _fh:
    TABLE = json.load(_fh)

MODELS = TABLE["models"]
CR_MULT = TABLE["default_cache_read_multiplier"]
CW_MULT = TABLE["default_cache_write_multiplier"]


def rates(model):
    """Return {in, out, cache_read, cache_write} USD per 1M tokens for a model id.

    Unknown ids fall back to the longest matching prefix, then to 'unknown'.
    """
    m = MODELS.get(model)
    if m is None:
        best = None
        for key in MODELS:
            if model and (model.startswith(key) or key in model):
                if best is None or len(key) > len(best):
                    best = key
        m = MODELS[best] if best else MODELS["unknown"]
    return {
        "in": m["in"],
        "out": m["out"],
        "cache_read": m.get("cache_read", m["in"] * CR_MULT),
        "cache_write": m.get("cache_write", m["in"] * CW_MULT),
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
