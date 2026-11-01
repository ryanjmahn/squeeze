"""Build docs/demo-data.js by running the real squeezers on the real fixtures, so the site can't drift from the tool."""
import json
import os
import re
from pathlib import Path

from squeeze import squeezers, stats
from squeeze.clean import clean

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUTPUT = ROOT / "docs" / "demo-data.js"

# (label, command shown, fixture, name in the header, argv for routing, exit code)
SCENARIOS = [
    ("pytest", "pytest -v", "pytest_failures_verbose", "pytest", ["pytest", "-v"], 1),
    ("jest", "jest", "jest_filtered_pass", "jest", ["jest"], 0),
    ("yarn", "yarn add request lodash", "yarn_install_success", "yarn", ["yarn", "add"], 0),
    ("tsc", "tsc --pretty", "tsc_errors_pretty", "tsc", ["tsc", "--pretty"], 1),
]


def _normal(line):
    return re.sub(r"\s+", " ", re.sub(r"^(?:E\s|>)", "", line)).strip().lower()


def _kept_lines(raw_lines, body):
    """Which raw lines made it into the output, so the animation can light up the right ones."""
    shown = [_normal(line) for line in body.split("\n")]
    kept = []
    for line in raw_lines:
        text = _normal(line)
        # tsc's pretty format reads differently from its squeezed form, so its error lines are matched by shape.
        kept.append("error ts" in text or (len(text) >= 6 and bool(re.search(r"\w", text)) and any(text in other for other in shown)))
    return kept if any(kept) else [False] * (len(raw_lines) - 1) + [True]


def build():
    scenarios = []
    for label, command, fixture, name, argv, code in SCENARIOS:
        raw = (FIXTURES / f"{fixture}.txt").read_text()
        body, _ = squeezers.squeeze(argv, raw, code)
        before = stats.measure(raw)
        report = f"🍋 {name} · exit {code} · 0.3s · {stats.summary(before, before)}\n\n{body}\n\nfull log: .squeeze/logs/{fixture}.log\n"
        after = stats.measure(report)
        header = f"🍋 {name} · exit {code} · {stats.summary(before, after)}"
        lines = clean(raw).split("\n")
        scenarios.append({
            "label": label,
            "command": command,
            "exit": code,
            "raw": lines,
            "kept": [int(k) for k in _kept_lines(lines, body)],
            "header": header,
            "body": body,
            "linesBefore": before[0],
            "linesAfter": after[0],
            "tokensBefore": stats.estimate_tokens(before[1]),
            "tokensAfter": stats.estimate_tokens(after[1]),
        })
    return "window.SQUEEZE_DEMO = " + json.dumps(scenarios, ensure_ascii=False) + ";\n"


if __name__ == "__main__":
    OUTPUT.write_text(build())
    print(f"wrote {os.path.relpath(OUTPUT)}")
