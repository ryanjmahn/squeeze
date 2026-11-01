"""TypeScript compiler: each error as file:line — message, plus the total."""
import re
from pathlib import Path

from ..clean import trim

NAMES = {"tsc", "vue-tsc"}
MAX_MESSAGE = 200  # type expansions can run to thousands of characters
MAX_DETAILS = 2

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

    rendered = list(dict.fromkeys(_render(error) for error in errors))
    files = {m["file"] or m["pfile"] for m in (error["match"] for error in errors)} - {None}
    count = f"{len(errors)} error{'s' if len(errors) != 1 else ''}"
    where = f" in {len(files)} file{'s' if len(files) != 1 else ''}" if files else ""
    return "\n".join([count + where, "", *rendered])


def _render(error):
    m = error["match"]
    path = m["file"] or m["pfile"]
    place = f"{path}:{m['line'] or m['pline']} — " if path else ""
    details = [trim(line, MAX_MESSAGE) for line in error["details"]]
    if len(details) > MAX_DETAILS:
        details = [*details[:MAX_DETAILS], f"  … {len(details) - MAX_DETAILS} more lines in the log …"]
    return "\n".join([f"{place}{m['code']}: {trim(m['message'], MAX_MESSAGE)}", *details])
