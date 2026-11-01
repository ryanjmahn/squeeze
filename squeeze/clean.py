"""Strip terminal noise and collapse repeated lines."""
import re

ERROR_RE = re.compile(r"error|fail|exception|fatal", re.IGNORECASE)

# CSI sequences (colors, cursor moves), OSC sequences (titles, links), then lone two-byte escapes.
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_NUMBER_RE = re.compile(r"0x[0-9a-fA-F]+|\d+")


def clean(raw):
    """Remove ANSI codes and overwritten progress-bar text. Returns the lines as one string."""
    # \r moves the cursor back so the next write overwrites the line; only the last write was ever visible.
    lines = (line.rstrip("\r").rsplit("\r", 1)[-1].rstrip() for line in _ANSI_RE.sub("", raw).split("\n"))
    return "\n".join(lines).rstrip("\n")


def _repeat_key(line):
    if not line.strip():
        return ""
    # Two errors differing only by a number can be different failures (file.py:10 vs file.py:20).
    return line if ERROR_RE.search(line) else _NUMBER_RE.sub("#", line)


def collapse_runs(lines):
    """Merge consecutive repeats into (line, count) pairs."""
    runs = []
    previous = None
    for line in lines:
        key = _repeat_key(line)
        if runs and key == previous:
            # Keep the newest line: "100%" and "epoch 50" say more than "1%" and "epoch 1".
            runs[-1] = (line, runs[-1][1] + 1)
        else:
            runs.append((line, 1))
        previous = key
    return runs


def render_run(line, count):
    return f"(× {count}) {line}" if count > 1 and line.strip() else line


def trim(line, limit=300):
    return line if len(line) <= limit else f"{line[:limit]}…"


def cap_error_lines(lines, limit=15):
    if len(lines) <= limit:
        return lines
    # The end of a chained exception or diff is what actually surfaced.
    return [*lines[: limit - 2], f"    … {len(lines) - limit} more lines in the log …", *lines[-2:]]
