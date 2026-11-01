"""The `sq` command."""
import argparse
import os
import re
import shutil
import sys
import time
from itertools import dropwhile

from . import dashboard, logs, records, runner, squeezers, stats

CLAUDE_SNIPPET = """\
## Squeeze (noisy commands)
- Run noisy commands through `sq`: tests, builds, installs, linters. Example: `sq pytest`, `sq npm install`.
- `sq` keeps the exit code and saves the full log. If you need more detail than the summary shows, read or grep the log path it prints instead of re-running the command.
- Use `sq --raw` only if the squeezed output is clearly missing something important.
- For pipes or `&&`, pass one quoted string: `sq -s "cd api && pytest"`.
"""


def _parser():
    parser = argparse.ArgumentParser(
        prog="sq",
        usage="sq [--raw] <command> [args...]\n       sq [--raw] -s \"<shell string>\"\n       sq init\n       sq stats [--week | --month | --all] [--repo]\n       sq stats --reset",
        description="Run a command, keep the full log on disk, print only what matters.",
    )
    parser.add_argument("--raw", action="store_true", help="show the normal output instead of squeezing it; the log is still saved")
    parser.add_argument("-s", dest="shell", metavar="STRING", help="run a shell string, for pipes and &&")
    # REMAINDER stops option parsing here, so flags after the command belong to the command.
    parser.add_argument("command", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def _shell_words(shell):
    """A shell string's words without leading VAR=value, whose values can be secrets and aren't the command."""
    return list(dropwhile(lambda word: re.match(r"^\w+=", word), shell.split()))


def _silence_stdout():
    # Whatever read our stdout has gone away (`sq cmd | head`). Keep the exit code and quiet the flush at shutdown.
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def _celebration(make_entry, tool, before, after):
    """The one line about a record or badge, or None. A bad history must never cost a command its output."""
    try:
        entry = make_entry(tool, before, after)
        # shortcut: re-reads the whole history each run (18ms per 10k runs), add a cache if that ever shows.
        return records.celebration(stats.load_history(), {**entry, "date": stats.entry_date(entry)})
    except Exception:
        return None


def _print_squeezed(name, words, code, elapsed, log_path, make_entry):
    """Print the report. Returns (squeezer name, size of the log, size of what was printed)."""
    out = sys.stdout.buffer
    tool = "none"
    before = after = (0, 0)
    try:
        raw, before = logs.read_for_squeezing(log_path)
        body, tool = squeezers.squeeze(words, raw, code)
        body = body.rstrip("\n")
        prefix = f"🍋 {name} · exit {code} · {elapsed:.1f}s · "
        footer = f"full log: {os.path.relpath(log_path)}"

        def render(summary):
            return "\n\n".join(part for part in (prefix + summary, body, footer) if part) + "\n"

        # "After" must count everything printed, including this summary, so measure a draft of it.
        draft = render(stats.summary(before, stats.measure(body)))
        report = render(stats.summary(before, stats.measure(draft)))
        after = stats.measure(report)
        if line := _celebration(make_entry, tool, before, after):
            report += f"{line}\n"
            after = stats.measure(report)
        out.write(report.encode("utf-8", "replace"))
        out.flush()
    except BrokenPipeError:
        _silence_stdout()
    except Exception as e:
        print(f"sq: could not squeeze, showing the raw log: {e}", file=sys.stderr)
        tool = "none"
        after = before
        try:
            with log_path.open("rb") as f:
                shutil.copyfileobj(f, out)
            out.flush()
        except BrokenPipeError:
            _silence_stdout()
        except OSError as e:
            print(f"sq: could not read the log: {e}", file=sys.stderr)
    return tool, before, after


def _print_raw_footer(name, code, elapsed, log_path):
    """The output already streamed past. Stderr keeps stdout identical to the unwrapped command's."""
    print(f"🍋 {name} · exit {code} · {elapsed:.1f}s · raw · full log: {os.path.relpath(log_path)}", file=sys.stderr)
    try:
        _, before = logs.read_for_squeezing(log_path)
    except OSError:
        before = (0, 0)
    return "none", before, before


def _reset_history():
    path = stats.history_path()
    runs = len(stats.load_history())
    if not path.exists():
        print("sq: no history to reset.")
        return 0
    print(f"This deletes {path} ({runs:,} runs, every stat, record and badge). It can't be undone.")
    try:
        answer = input("Delete it? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Nothing deleted.")
        return 0
    path.unlink()
    print("History deleted.")
    return 0


def _stats(argv):
    parser = argparse.ArgumentParser(prog="sq stats", description="Your tokens saved, Strava-style.")
    period = parser.add_mutually_exclusive_group()
    period.add_argument("--week", dest="period", action="store_const", const="week", help="this week (the default)")
    period.add_argument("--month", dest="period", action="store_const", const="month", help="this month")
    period.add_argument("--all", dest="period", action="store_const", const="all", help="all time")
    parser.add_argument("--repo", action="store_true", help="only the current repo")
    parser.add_argument("--reset", action="store_true", help="delete your history, after asking")
    args = parser.parse_args(argv)
    if args.reset:
        if args.period or args.repo:
            parser.error("--reset deletes all history, so it can't be combined with other options")
        return _reset_history()

    entries = stats.load_history()
    repo = logs.find_root().name if args.repo else None
    if repo:
        entries = [entry for entry in entries if entry["repo"] == repo]
    if not entries:
        print(f"No squeezes yet{f' in {repo}' if repo else ''}. Try: sq pytest")
        return 0
    print(dashboard.render(entries, args.period or "week", repo=repo))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["init"]:
        print("sq: paste this into your CLAUDE.md (or run: sq init >> CLAUDE.md)", file=sys.stderr)
        sys.stdout.write(CLAUDE_SNIPPET)
        return 0
    if argv[:1] == ["stats"]:
        return _stats(argv[1:])

    parser = _parser()
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if bool(args.shell is not None) == bool(command):
        parser.error("give either a command or -s, not both" if command else "no command given")

    if args.shell is not None:
        run_argv = ["/bin/sh", "-c", args.shell]
        words = _shell_words(args.shell)
    else:
        run_argv = command
        words = command
    name = logs.safe_name(words[0]) if words else "sh"

    root = logs.find_root()
    try:
        if logs.ensure_gitignored(root):
            print(f"sq: added .squeeze/ to {root / '.gitignore'}", file=sys.stderr)
    except OSError as e:
        print(f"sq: warning: could not update .gitignore, logs may get committed: {e}", file=sys.stderr)

    try:
        log_path, log_file = logs.open_log(root, name)
    except OSError as e:
        print(f"sq: cannot write log, command not run: {e}", file=sys.stderr)
        return 125  # distinct from anything the command itself could mean by 126/127

    start = time.monotonic()
    with log_file:
        code = runner.run(run_argv, log_file, raw=args.raw)
    elapsed = time.monotonic() - start

    def make_entry(tool, before, after):
        return stats.new_entry(root.name, name, tool, code, elapsed, before, after, args.raw)

    if args.raw:
        tool, before, after = _print_raw_footer(name, code, elapsed, log_path)
    else:
        tool, before, after = _print_squeezed(name, words, code, elapsed, log_path, make_entry)

    # Bookkeeping must never change the command's exit code.
    try:
        stats.append(make_entry(tool, before, after))
    except OSError as e:
        print(f"sq: could not update history: {e}", file=sys.stderr)
    try:
        logs.rotate(log_path)
    except OSError as e:
        print(f"sq: could not remove old logs: {e}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
