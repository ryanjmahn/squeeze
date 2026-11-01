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
        # shortcut: loads the whole log into memory, stream it if multi-GB logs show up.
        raw = log_path.read_bytes().decode("utf-8", "replace")
        body = squeezers.squeeze(argv, raw, code).rstrip("\n")
        # shortcut: the "after" count skips the header and footer, so it reads about 3 lines low.
        header = f"🍋 {Path(argv[0]).name} · exit {code} · {elapsed:.1f}s · {stats.summary(raw, body)}"
        footer = f"full log: {os.path.relpath(log_path)}"
        report = "\n\n".join(part for part in (header, body, footer) if part) + "\n"
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
