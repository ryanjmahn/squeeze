"""Find where logs live, create them, read them back, keep them out of git."""
import os
import re
import time
from itertools import count
from pathlib import Path

from .clean import ERROR_RE
from .stats import measure

DEFAULT_KEEP_LOGS = 50
MAX_WHOLE_BYTES = 64 * 1024 * 1024
HEAD_BYTES = 1024 * 1024
TAIL_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_MIDDLE_ERRORS = 200


def find_root(start=None):
    """The enclosing git repo's root, or the current directory if not in a repo."""
    cwd = Path(start or Path.cwd())
    return next((p for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd)


def ensure_gitignored(root):
    """Add .squeeze/ to the repo's .gitignore. Returns True if it had to be added."""
    if not (root / ".git").exists():
        return False
    path = root / ".gitignore"
    # Bytes, because a .gitignore isn't guaranteed to be valid UTF-8.
    text = path.read_bytes() if path.exists() else b""
    if any(line.strip() in (b".squeeze", b".squeeze/", b"/.squeeze/") for line in text.splitlines()):
        return False
    with path.open("ab") as f:
        f.write((b"\n" if text and not text.endswith(b"\n") else b"") + b".squeeze/\n")
    return True


def safe_name(command):
    """A command's name without its directory, safe to use in a filename."""
    return re.sub(r"[^\w.-]", "_", Path(command).name)[:50]


def open_log(root, name):
    """Create a new log file for a command. Returns (path, open binary file)."""
    log_dir = root / ".squeeze" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{time.strftime('%Y-%m-%d_%H%M%S')}_{name}"
    # Mode "x" refuses to overwrite, so parallel runs in the same second can't clobber a log.
    for n in count(1):
        path = log_dir / (f"{stem}.log" if n == 1 else f"{stem}-{n}.log")
        try:
            return path, path.open("xb")
        except FileExistsError:
            pass


def _modified_time(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0  # a parallel run just removed it


def keep_count():
    """How many logs to keep: SQUEEZE_KEEP_LOGS, or the default if that isn't a positive number."""
    value = os.environ.get("SQUEEZE_KEEP_LOGS", "")
    return int(value) if value.isdecimal() and int(value) > 0 else DEFAULT_KEEP_LOGS


def rotate(current):
    """Delete the oldest logs beside current. Current is never deleted: its path was just printed."""
    newest_first = sorted(current.parent.glob("*.log"), key=_modified_time, reverse=True)
    for old in newest_first[keep_count():]:
        if old != current:
            old.unlink(missing_ok=True)


def read_for_squeezing(path):
    """Returns (text, (lines, characters) of the whole log).

    A log too big to hold in memory comes back as its start, the error lines from
    its middle, and its end, which is where tools print their results.
    """
    size = path.stat().st_size
    if size <= MAX_WHOLE_BYTES:
        text = path.read_bytes().decode("utf-8", "replace")
        return text, measure(text)

    errors = {}
    tail_start = size - TAIL_BYTES
    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
        lines = head.count(b"\n")
        while f.tell() < tail_start:
            line = f.readline(MAX_LINE_BYTES)
            lines += line.endswith(b"\n")
            if len(errors) < MAX_MIDDLE_ERRORS:
                text = line.decode("utf-8", "replace").rstrip("\n")
                if ERROR_RE.search(text):
                    errors[text] = None
        # Carry on from where the loop stopped: the last line it read can cross tail_start.
        tail = f.read()
    note = f"… log too large to read whole, showing up to {MAX_MIDDLE_ERRORS} error lines from its middle …"
    text = "\n".join([head.decode("utf-8", "replace"), note, *errors, tail.decode("utf-8", "replace")])
    return text, (lines + tail.count(b"\n"), size)
