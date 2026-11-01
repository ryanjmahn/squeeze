# Squeezers

## Supported tools

| Tool | Keeps | Drops |
|---|---|---|
| **pytest** | totals, each failure's last frames in your code, the error, the end of what it printed | passing tests, dependency frames, repeated warnings (as a count) |
| **jest, vitest** | totals, failing tests, assertion diffs, console output from failing files | passing suites and their console noise |
| **npm, pnpm, yarn** installs | the result, errors, peer conflicts, anything unrecognized | progress, funding notices, deprecations (as a count) |
| **pip, uv pip** installs | the result (shortened), errors, build failures, anything unrecognized | download lines, "already satisfied" (as a count) |
| **tsc** | each error as `file:line — message`, the total | duplicates, long type expansions (truncated) |
| **anything else** | the first lines, the last lines, and any line with error/fail/exception/fatal plus context | everything else, with a note like `… 640 lines hidden …` |

## Real numbers

Measured on sample projects and real ones, counting the header and footer Squeeze adds. Tokens are estimated as characters ÷ 4. Yours will differ, and a very short command can cost a few tokens rather than save them.

| Run | Lines | Tokens (est.) |
|---|---|---|
| `pytest -v`, all passing, a real project | 151 → 5 | ~3.2k → ~44 |
| `jest`, all passing, noisy logs | 155 → 5 | ~737 → ~42 |
| `pytest -v`, all passing | 70 → 5 | ~1.3k → ~38 |
| `pip install flask` | 14 → 5 | ~409 → ~46 |
| `pytest -v`, 7 failures | 237 → 46 | ~3.0k → ~496 |
| `jest --verbose`, 5 failures | 248 → 47 | ~1.4k → ~402 |
| `tsc --pretty`, 8 errors | 53 → 16 | ~616 → ~220 |
| `vitest run`, 5 failures | 108 → 49 | ~776 → ~420 |
| `npm install` | 12 → 6 | ~64 → ~53 |

## Adding a squeezer

A squeezer is one file in `squeeze/squeezers/` with two functions. `output` has already had colors and progress bars removed. Raise an error whenever the output isn't what you expected, and Squeeze falls back to the generic squeezer.

```python
# squeeze/squeezers/cargo.py
"""cargo test: the result line and each failing test."""
import re
from pathlib import Path


def matches(command, output):
    return Path(command[0]).name == "cargo" and "test" in command


def squeeze(output, exit_code):
    result = re.search(r"^test result: .*$", output, re.MULTILINE)
    if not result:
        raise ValueError("no test result found, so this run may have crashed")
    if exit_code == 0:
        return f"✓ {result[0]}"
    failed = re.findall(r"^test (\S+) \.\.\. FAILED$", output, re.MULTILINE)
    if not failed:
        raise ValueError("failed, but no failing test found")
    return "\n".join([result[0], *(f"✗ {name}" for name in failed)])
```

Then list it in `SQUEEZERS` in [`squeeze/squeezers/__init__.py`](../squeeze/squeezers/__init__.py), and save real output from the tool in `tests/fixtures/`. Real output is what catches the formats you wouldn't have guessed.
