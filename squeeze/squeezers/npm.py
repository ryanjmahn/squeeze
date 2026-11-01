"""npm, pnpm and yarn installs. Drops known noise and keeps everything else, because a
failing install script's real error is ordinary output with no "npm error" prefix."""
import re
from pathlib import Path

from . import generic

MANAGERS = {"npm", "pnpm", "yarn"}
INSTALL_COMMANDS = {"install", "i", "add", "ci", "update", "up", "upgrade", "remove", "rm", "uninstall"}

_DEPRECATED_RE = re.compile(
    r"^npm (?:warn|WARN) deprecated "  # npm 10 and later use lowercase, earlier use capitals
    r"|^\s*(?:\[WARN\]|WARN)\s+(\d+ )?deprecated"
    r'|^warning [^"].*@\d.*: '  # yarn 1; its peer warnings start with a quote and are kept
    r"|^➤ YN0061:"  # yarn 2+
)
_RESULT_RE = re.compile(
    r"^(?:added|removed|changed|audited|up to date)\b"
    r"|^Packages: "
    r"|^Done in "
    r"|^success (?:Saved \d+ new|Already up-to-date)"
    r"|^➤ YN0013: │ \d+ packages? (?:was|were) added"
    r"|^➤ YN0000: · Done"
)
_YARN_PREFIX_RE = re.compile(r"^➤ YN\d+: [│·] ")
_NOISE_RE = re.compile(
    r"^npm (?:error|ERR!|warn|WARN)(?: 404)?\s*$"
    r"|^npm (?:error|ERR!) A complete log of this run"
    r"|^\d+ packages? (?:is|are) looking for funding"
    r"|^\s*run `npm fund`"
    r"|^found 0 vulnerabilities"
    r"|^Some issues need review"
    r"|^a different dependency"
    r"|^Run `npm audit`"
    r"|^To address "
    r"|^\s*npm audit fix"
    r"|^Packages are (?:cloned|hard linked|copied)"
    r"|^\s*(?:Content-addressable store|Virtual store) is at"
    r"|^\++$"
    r"|^Progress: "
    r"|^(?:dev|optional)?[dD]ependencies:$"
    r"|^[+-] \S+ \d\S*(?: deprecated)?$"  # pnpm's package list, and not a script's "- something failed"
    r"|^yarn \w+ v\d"
    r"|^\[\d+/\d+\] "
    r"|^info (?:No lockfile|Direct dependencies|All dependencies|Visit )"
    r"|^success Saved lockfile"
    r"|^[├└]─ "
    r"|^\s+at .*(?:node_modules|node:)"  # only stack frames from outside the project
    r"|^➤ YN0000: (?:[┌└]|· Yarn )"
    r"|^➤ YN0085:"
)


def matches(command, output):
    name = Path(command[0]).name
    words = [arg for arg in command[1:] if not arg.startswith("-")]
    return name in MANAGERS and (words[0] in INSTALL_COMMANDS if words else name == "yarn")


def squeeze(output, exit_code):
    deprecated = 0
    results = []
    rest = []
    for line in output.split("\n"):
        if not line.strip() or _NOISE_RE.match(line):
            continue
        if m := _DEPRECATED_RE.match(line):
            deprecated += int(m[1] or 1) if m.lastindex else 1
        elif exit_code == 0 and _RESULT_RE.match(line):
            results.append(_YARN_PREFIX_RE.sub("", line))
        else:
            rest.append(line)

    if exit_code == 0 and not results:
        raise ValueError("no install result found")
    if exit_code != 0 and not rest:
        raise ValueError("failed, but nothing but noise to show")

    parts = [f"✓ {' · '.join(results)}"] if results else []
    if rest:
        # Passing "failed" keeps the longer tail: peer-conflict warnings are worth it even on success.
        parts.append(generic.squeeze("\n".join(rest), 1))
    if deprecated:
        parts.append(f"⚠ {deprecated} deprecated package{'s' if deprecated != 1 else ''} — hidden")
    return "\n".join(parts)
