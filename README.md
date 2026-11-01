<div align="center">

# Squeeze 🍋

A log squeezer for coding agents.

[![Stars](https://img.shields.io/github/stars/YOUR_REAL_NAME/squeeze?style=flat&color=black)](https://github.com/YOUR_REAL_NAME/squeeze/stargazers)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-black.svg)](https://www.python.org)
[![Dependencies: none](https://img.shields.io/badge/Dependencies-none-black.svg)](pyproject.toml)

</div>

You type `sq pytest` instead of `pytest`, and your agent reads 12 lines instead of 77. That is the whole idea. Squeeze runs the command, saves the full log to disk, and prints only the summary, the failures, and the lines that explain them. The exit code does not change.

**Before:** 77 lines of `pytest -v`, with passing tests, a traceback, and 40 copies of the same warning.

**After:**

```
🍋 pytest · exit 1 · 0.2s · 77 lines → 12 lines (-84%) · ~1.3k → ~111 tokens (est.)

1 failed, 40 passed, 4 deselected, 40 warnings in 0.03s

✗ tests/test_auth.py::test_refresh_token
    tests/test_auth.py:6  assert refresh({"token": "abc"}) == 2
    auth/tokens.py:5  return token["expires_at"] + 1
    KeyError: 'expires_at'

⚠ 40 warnings (DeprecationWarning ×40 from utils/dates.py) — hidden

full log: .squeeze/logs/2026-11-01_205057_pytest.log
```

> **Squeeze runs entirely on your machine.** There is no account and no server, and nothing is uploaded. Your stats stay in a local file that only you can read. See [privacy](docs/usage.md#privacy).

> If this saves your agent some context, a star on the repo genuinely helps other people find it.

## Why this exists

When a coding agent runs a command, every line of test output and install spam lands in its context window. Most of it is noise. The agent burns tokens, loses focus, and forgets earlier work sooner.

Piping to `tail -20` saves the tokens, but it can cut off the actual error, and the rest of the output is gone. Squeeze keeps the failures, keeps the exit code, and saves the full log, so the agent can read or grep the file instead of running the command again.

## Features

- Per-tool squeezers. pytest, jest, vitest, npm, pnpm, yarn, pip, uv pip, and tsc each get a parser built from their real output. See [supported tools](docs/squeezers.md#supported-tools).
- Generic fallback. Any other command keeps its first lines, its last lines, and every line that looks like an error, with a little context.
- Real savings. A noisy `jest` run went from about 737 tokens to 42 in testing, though a very short command can cost a few tokens. See [real numbers](docs/squeezers.md#real-numbers).
- Exact exit codes. If `pytest` exits 1, `sq pytest` exits 1. A command killed by a signal exits the way it would in a shell.
- Full logs on disk. Every run is saved to `.squeeze/logs/`, the newest 50 are kept, and `.squeeze/` is added to `.gitignore` automatically.
- Repeat collapsing. Identical lines become `(× 37) DeprecationWarning: ...`, and colors and progress bars are stripped first.
- Easy to extend. A new squeezer is one file with two functions. See [adding a squeezer](docs/squeezers.md#adding-a-squeezer).
- Shell strings. `sq -s "cd api && pytest"` handles pipes and `&&`.
- Raw mode. `sq --raw pytest` shows the normal output live and still saves the log.
- Strava-style stats. `sq stats` shows tokens saved, your streak, daily bars, personal records, and badges. See [usage](docs/usage.md).
- Shareable cards. `sq card` makes a self-contained HTML page and an SVG you can drop into a GitHub profile.

## How it works

1. You or your agent runs `sq <command>`.
2. Squeeze runs the command with stdout and stderr going straight to a log file, so their order is kept and a partial log survives Ctrl+C.
3. It strips colors and overwritten progress bars from a copy of the output.
4. It picks a squeezer from the command name, or from the output for wrappers like `npm test` and `make test`.
5. It prints the summary and the path to the full log, then exits with the command's own exit code.

Squeezing can never hide a failure. If a squeezer crashes, returns nothing, or finds a different number of failures than the tool reported, the generic squeezer takes over. If that fails too, you get the raw output. A ✓ only ever means exit 0, so a coverage threshold that fails a run where every test passed shows the reason instead.

## Quick start

Squeeze needs Python 3.10 or newer and has no dependencies. [pipx](https://pipx.pypa.io) puts `sq` on your `PATH` everywhere, which is what an agent needs.

```bash
pipx install git+https://github.com/YOUR_REAL_NAME/squeeze
sq init >> CLAUDE.md      # tells your agent to use sq
sq pytest                 # or any noisy command
sq stats                  # see what you saved
```

Every command and flag is in [docs/usage.md](docs/usage.md).

### Run it locally

```bash
git clone https://github.com/YOUR_REAL_NAME/squeeze.git
cd squeeze
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests
```

## Set it up with your AI assistant

The savings only happen when your agent actually uses `sq`. `sq init` prints this snippet for your `CLAUDE.md`:

```md
## Squeeze (noisy commands)
- Run noisy commands through `sq`: tests, builds, installs, linters. Example: `sq pytest`, `sq npm install`.
- `sq` keeps the exit code and saves the full log. If you need more detail than the summary shows, read or grep the log path it prints instead of re-running the command.
- Use `sq --raw` only if the squeezed output is clearly missing something important.
- For pipes or `&&`, pass one quoted string: `sq -s "cd api && pytest"`.
```

## Tech stack

- Python 3.10+, standard library only
- `subprocess` and `selectors` for running commands and streaming `--raw` output
- Plain JSONL for the local history
- Inline SVG for the shareable card, with no external fonts or scripts
- `unittest`, with real captured tool output as fixtures

## Contributing

Issues and pull requests are welcome. If a tool's output gets squeezed badly, a saved copy of that output is worth as much as a code fix, because real output is what the tests are built on. To add a tool, see [adding a squeezer](docs/squeezers.md#adding-a-squeezer), and for what's planned, see the [roadmap](docs/roadmap.md).

## Credits

Built and maintained by [@YOUR_REAL_NAME](https://github.com/YOUR_REAL_NAME).

## Star the repo

If Squeeze is useful to you, star it. It is the simplest way to help the project reach the next person whose agent is drowning in test output.
