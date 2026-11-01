"""Find where logs live, create them, keep them out of git."""
import re
import time
from itertools import count
from pathlib import Path


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


def open_log(root, command):
    """Create a new log file for command. Returns (path, open binary file)."""
    log_dir = root / ".squeeze" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]", "_", Path(command).name)[:50]
    stem = f"{time.strftime('%Y-%m-%d_%H%M%S')}_{name}"
    # Mode "x" refuses to overwrite, so parallel runs in the same second can't clobber a log.
    for n in count(1):
        path = log_dir / (f"{stem}.log" if n == 1 else f"{stem}-{n}.log")
        try:
            return path, path.open("xb")
        except FileExistsError:
            pass
