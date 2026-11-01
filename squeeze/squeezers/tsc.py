"""TypeScript compiler: each error as file:line — message, plus the total."""
import re
from collections import Counter
from pathlib import Path

from ..clean import trim

NAMES = {"tsc", "vue-tsc"}
MAX_MESSAGE = 200  # type expansions can run to thousands of characters
MAX_DETAILS = 2
MAX_ERRORS = 50
MAX_OVERFLOW_FILES = 5

_ERROR_RE = re.compile(
    r"^(?:(?P<file>.+?)\((?P<line>\d+),\d+\): |(?P<pfile>.+?):(?P<pline>\d+):\d+ - )?"
    r"error (?P<code>TS\d+): (?P<message>.*)$"
)
_FOUND_RE = re.compile(r"^Found (\d+) errors?\b", re.MULTILINE)


def matches(command, output):
    return any(Path(arg).name in NAMES for arg in command) or any(_ERROR_RE.match(line) for line in output.split("\n"))


def squeeze(output, exit_code):
    lines = output.split("\n")
    errors = []
    current = None
    for line in lines:
        if m := _ERROR_RE.match(line):
            current = {"match": m, "details": []}
            errors.append(current)
        elif not line.strip():
            current = None  # --pretty puts the source listing after a blank line
        elif current and line.startswith("  "):
            current["details"].append(line)
        else:
            current = None

    # With --pretty, tsc states its own count: never report fewer than it did.
    found = _FOUND_RE.search(output)
    if found and int(found[1]) != len(errors):
        raise ValueError(f"parsed {len(errors)} errors, tsc reported {found[1]}")
    if not errors:
        if exit_code == 0 and not output.strip():
            return "✓ no type errors"
        # Exit 0 with output is --listFiles or --version; a failure with no errors is unexplained.
        raise ValueError("no type errors to report")

    unique = {_render(error): _path(error) for error in errors}
    files = set(unique.values()) - {None}
    count = f"{len(errors)} error{'s' if len(errors) != 1 else ''}"
    where = f" in {len(files)} file{'s' if len(files) != 1 else ''}" if files else ""
    return "\n".join([count + where, "", *list(unique)[:MAX_ERRORS], *_overflow(list(unique.values())[MAX_ERRORS:])])


def _overflow(paths):
    """Fixing the first errors often clears the rest, so the remainder only needs to say where it is."""
    if not paths:
        return []
    counts = Counter(path or "(no file)" for path in paths)
    worst = ", ".join(f"{path} ×{n}" for path, n in counts.most_common(MAX_OVERFLOW_FILES))
    more = f", +{len(counts) - MAX_OVERFLOW_FILES} more files" if len(counts) > MAX_OVERFLOW_FILES else ""
    return [f"… {len(paths)} more errors in the log: {worst}{more}"]


def _path(error):
    return error["match"]["file"] or error["match"]["pfile"]


def _render(error):
    m = error["match"]
    path = _path(error)
    place = f"{path}:{m['line'] or m['pline']} — " if path else ""
    details = [trim(line, MAX_MESSAGE) for line in error["details"]]
    if len(details) > MAX_DETAILS:
        details = [*details[:MAX_DETAILS], f"  … {len(details) - MAX_DETAILS} more lines in the log …"]
    return "\n".join([f"{place}{m['code']}: {trim(m['message'], MAX_MESSAGE)}", *details])
