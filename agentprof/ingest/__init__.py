from . import claude_code, ndjson  # noqa: F401

READERS = {
    "claude-code": claude_code.read,
    "ndjson": ndjson.read,
}


def read_auto(path):
    """Sniff the format of a log file and return (format_name, events)."""
    name = ndjson.sniff(path) or "claude-code"
    return name, READERS[name](path)
