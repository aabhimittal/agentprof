from . import claude_code, ndjson, openai_log  # noqa: F401

READERS = {
    "claude-code": claude_code.read,
    "ndjson": ndjson.read,
    "openai": openai_log.read,
}
SNIFFERS = (ndjson.sniff, openai_log.sniff)


def read_auto(path):
    """Sniff the format of a log file and return (format_name, events)."""
    name = None
    for sniff in SNIFFERS:
        name = sniff(path)
        if name:
            break
    name = name or "claude-code"
    return name, READERS[name](path)
