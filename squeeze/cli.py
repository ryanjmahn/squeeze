"""The `sq` command."""
import argparse
import os
import re
import shutil
import sys
import time
from itertools import dropwhile

from . import logs, runner, squeezers, stats

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
        usage="sq [--raw] <command> [args...]\n       sq [--raw] -s \"<shell string>\"\n       sq init",
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


def _print_squeezed(name, words, code, elapsed, log_path):
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["init"]:
        print("sq: paste this into your CLAUDE.md (or run: sq init >> CLAUDE.md)", file=sys.stderr)
        sys.stdout.write(CLAUDE_SNIPPET)
        return 0

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

    if args.raw:
        tool, before, after = _print_raw_footer(name, code, elapsed, log_path)
    else:
        tool, before, after = _print_squeezed(name, words, code, elapsed, log_path)

    # Bookkeeping must never change the command's exit code.
    try:
        stats.record(root.name, name, tool, code, elapsed, before, after, args.raw)
    except OSError as e:
        print(f"sq: could not update history: {e}", file=sys.stderr)
    try:
        logs.rotate(log_path)
    except OSError as e:
        print(f"sq: could not remove old logs: {e}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
