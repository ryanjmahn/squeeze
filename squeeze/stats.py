"""Line and token estimates, and the global history of runs."""
import json
import os
from datetime import datetime
from pathlib import Path

HISTORY_VERSION = 1


def measure(text):
    """(lines, characters), the numbers everything else here works from."""
    return len(text.splitlines()), len(text)


def estimate_tokens(chars):
    return chars // 4


def _format_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _format_lines(n):
    return f"{n} line" if n == 1 else f"{n} lines"


def summary(before, after):
    """Like: 812 lines → 19 lines (-97%) · ~5.2k → ~320 tokens (est.)"""
    lines_before, chars_before = before
    lines_after, chars_after = after
    # int() rounds down, so -99.8% never displays as a -100% that would claim nothing is left.
    saved = f" (-{int(100 * (1 - lines_after / lines_before))}%)" if lines_after < lines_before else ""
    return (
        f"{_format_lines(lines_before)} → {_format_lines(lines_after)}{saved}"
        f" · ~{_format_tokens(estimate_tokens(chars_before))} → ~{_format_tokens(estimate_tokens(chars_after))} tokens (est.)"
    )


def history_path():
    return Path.home() / ".squeeze" / "history.jsonl"


def format_compact(n):
    """Like: 1.24M, 182k, 4.8k, 950."""
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 10_000:
        return f"{n / 1000:.0f}k"
    return f"{n / 1000:.1f}k" if abs(n) >= 1000 else str(n)


def saved(entry):
    """Tokens this run saved. Short commands can go negative: the header costs more than it removed."""
    return 0 if entry["raw"] else entry["tokens_before"] - entry["tokens_after"]


def entry_date(entry):
    # The offset recorded with the run, so moving timezones doesn't rewrite past days.
    return datetime.fromisoformat(entry["ts"]).date()


def load_history():
    """Every readable run, oldest first, each with its "date". A damaged line is skipped, not fatal."""
    try:
        text = history_path().read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    entries = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
            if entry["v"] == HISTORY_VERSION:
                saved(entry)
                entry["date"] = entry_date(entry)
                entries.append(entry)
        except (ValueError, KeyError, TypeError):
            pass
    return entries


def new_entry(repo, command, tool, exit_code, seconds, before, after, raw):
    """One run, for the history. Only names and numbers: never arguments or output, which can hold secrets."""
    return {
        "v": HISTORY_VERSION,
        # Local time with its offset, so a day and a streak mean what they meant when the run happened.
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo": repo,
        "command": command,
        "tool": tool,
        "exit": exit_code,
        "seconds": round(seconds, 1),
        "lines_before": before[0],
        "lines_after": after[0],
        "tokens_before": estimate_tokens(before[1]),
        "tokens_after": estimate_tokens(after[1]),
        "raw": raw,
    }


def append(entry):
    path = history_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # One write in append mode, so parallel runs can't interleave inside a line.
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(entry, ensure_ascii=False) + "\n").encode())
    finally:
        os.close(fd)
