"""The `sq` command."""
import os
import shutil
import sys
import time
from pathlib import Path

from . import logs, runner, squeezers, stats

USAGE = "usage: sq <command> [args...]\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(USAGE)
        return 0 if argv else 2

    root = logs.find_root()
    try:
        if logs.ensure_gitignored(root):
            print(f"sq: added .squeeze/ to {root / '.gitignore'}", file=sys.stderr)
    except OSError as e:
        print(f"sq: warning: could not update .gitignore, logs may get committed: {e}", file=sys.stderr)

    try:
        log_path, log_file = logs.open_log(root, argv[0])
    except OSError as e:
        print(f"sq: cannot write log, command not run: {e}", file=sys.stderr)
        return 125  # distinct from anything the command itself could mean by 126/127

    start = time.monotonic()
    with log_file:
        code = runner.run(argv, log_file)
    elapsed = time.monotonic() - start

    out = sys.stdout.buffer
    try:
        raw, before = logs.read_for_squeezing(log_path)
        body = squeezers.squeeze(argv, raw, code).rstrip("\n")
        prefix = f"🍋 {Path(argv[0]).name} · exit {code} · {elapsed:.1f}s · "
        footer = f"full log: {os.path.relpath(log_path)}"

        def render(summary):
            return "\n\n".join(part for part in (prefix + summary, body, footer) if part) + "\n"

        # "After" must count everything printed, including this summary, so measure a draft of it.
        draft = render(stats.summary(before, stats.measure(body)))
        report = render(stats.summary(before, stats.measure(draft)))
        out.write(report.encode("utf-8", "replace"))
        out.flush()
    except BrokenPipeError:
        # `sq cmd | head` closed our stdout. Keep the exit code; silence the flush at shutdown.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except Exception as e:
        print(f"sq: could not squeeze, showing the raw log: {e}", file=sys.stderr)
        with log_path.open("rb") as f:
            shutil.copyfileobj(f, out)
        out.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
