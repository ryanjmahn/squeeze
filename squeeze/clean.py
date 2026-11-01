"""Strip terminal noise and collapse repeated lines."""
import re

ERROR_RE = re.compile(r"error|fail|exception|fatal", re.IGNORECASE)

# CSI sequences (colors, cursor moves), OSC sequences (titles, links), then lone two-byte escapes.
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_NUMBER_RE = re.compile(r"0x[0-9a-fA-F]+|\d+")
_BACKSPACE_RE = re.compile(r"[^\n\x08]\x08")


def _apply_backspaces(text):
    # Spinners draw with "|\b/\b-\b": each backspace erases the character before it.
    while "\x08" in text:
        text, erased = _BACKSPACE_RE.subn("", text)
        if not erased:
            return text.replace("\x08", "")
    return text


def clean(raw):
    """Remove ANSI codes and overwritten progress-bar text. Returns the lines as one string."""
    text = _apply_backspaces(_ANSI_RE.sub("", raw))
    # \r moves the cursor back so the next write overwrites the line; only the last write was ever visible.
    lines = (line.rstrip("\r").rsplit("\r", 1)[-1].rstrip() for line in text.split("\n"))
    return "\n".join(lines).rstrip("\n")


def _repeat_key(line):
    if not line.strip():
        return ""
    # Two errors differing only by a number can be different failures (file.py:10 vs file.py:20),
    # and in a line with no words the numbers are the data.
    if ERROR_RE.search(line) or not re.search(r"[^\W\d]", line):
        return line
    return _NUMBER_RE.sub("#", line)


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
    return line if len(line) <= limit else f"{line[:limit]}… (+{len(line) - limit} chars in the log)"


def last_lines(lines, count=5):
    if len(lines) <= count:
        return lines
    return [f"… {len(lines) - count} earlier lines in the log …", *lines[-count:]]


def cap_error_lines(lines, limit=15):
    if len(lines) <= limit:
        return lines
    # The end of a chained exception or diff is what actually surfaced.
    return [*lines[: limit - 2], f"    … {len(lines) - limit} more lines in the log …", *lines[-2:]]
