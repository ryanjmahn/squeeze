"""pip install and uv pip install. Drops known noise and keeps everything else, so a build
failure's output and any warning format we haven't seen still get shown."""
import re
from pathlib import Path

from . import generic

SHOW_PACKAGES = 3

_PIP_RE = re.compile(r"^pip\d*(\.\d+)*$")
_SATISFIED_RE = re.compile(r"^Requirement already satisfied")
_UV_RESULT_RE = re.compile(r"^(?:Installed|Audited|Checked) \d+ packages? in ")
_NOISE_RE = re.compile(
    r"^\s*(?:Collecting|Downloading|Using cached|Using legacy|Processing|Obtaining|Looking in indexes"
    r"|Installing collected packages|Attempting uninstall|Found existing installation|Uninstalling"
    r"|Successfully uninstalled|Successfully built|Building wheels? for|Building editable for"
    r"|Created wheel|Stored in directory|Saved |Checking if build backend)\b"
    r"|^\[notice\]"
    r"|^INFO: pip is looking at"
    # Build steps that went fine. A step that finished with status 'error' stays.
    r"|^\s+.*: (?:started|finished with status 'done')$"
    r"|^\s*━"  # a progress bar
    # uv
    r"|^Using Python .* environment at"
    r"|^(?:Resolved|Prepared|Uninstalled) \d+ packages? in "
    r"|^ [-+~] \S+==\S+$"
)


def matches(command, output):
    return "install" in command and any(_PIP_RE.match(Path(arg).name) for arg in command)


def squeeze(output, exit_code):
    satisfied = 0
    installed = []
    results = []
    rest = []
    for line in output.split("\n"):
        if not line.strip() or _NOISE_RE.match(line):
            continue
        if _SATISFIED_RE.match(line):
            satisfied += 1
        elif exit_code == 0 and line.startswith("Successfully installed "):
            installed = line.split()[2:]
        elif exit_code == 0 and _UV_RESULT_RE.match(line):
            results.append(line)
        else:
            rest.append(line)

    if exit_code == 0 and not installed and not satisfied and not results:
        raise ValueError("no install result found")
    if exit_code != 0 and not rest:
        raise ValueError("failed, but nothing but noise to show")

    if exit_code != 0:
        # A failed install can still have satisfied requirements. That's not worth a ✓.
        satisfied = 0
    if installed:
        shown = ", ".join(installed[:SHOW_PACKAGES])
        more = f", +{len(installed) - SHOW_PACKAGES} more" if len(installed) > SHOW_PACKAGES else ""
        results.append(f"installed {len(installed)} package{'s' if len(installed) != 1 else ''}: {shown}{more}")
    if satisfied:
        results.append(f"{satisfied} already satisfied")

    parts = [f"✓ {' · '.join(results)}"] if results else []
    if rest:
        parts.append(generic.squeeze("\n".join(rest), 1))
    return "\n".join(parts)
