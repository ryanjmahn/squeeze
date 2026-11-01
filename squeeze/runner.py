"""Run a command with all of its output going to a log file."""
import os
import signal
import subprocess


def run(argv, log_file):
    """Run argv, writing stdout and stderr to log_file. Returns a shell-style exit code."""
    proc = None

    def forward(signum, _frame):
        # A terminal's Ctrl+C already reaches the child (same process group), and
        # sending it twice makes many tools force-quit, so only forward when no
        # terminal delivered it.
        # shortcut: `... | sq cmd` at a terminal still sends Ctrl+C twice, fix if a tool misbehaves.
        if proc and (signum == signal.SIGTERM or not os.isatty(0)):
            proc.send_signal(signum)

    previous = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        # The child writes straight to the file: both streams stay in order, a
        # partial log survives any interruption, and a daemon the command leaves
        # behind can't hang us the way it would by holding a pipe open.
        proc = subprocess.Popen(argv, stdout=log_file, stderr=subprocess.STDOUT)
        returncode = proc.wait()
    except FileNotFoundError:
        log_file.write(f"sq: command not found: {argv[0]}\n".encode())
        return 127
    except OSError as e:
        log_file.write(f"sq: cannot run {argv[0]}: {e}\n".encode())
        return 126
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)

    # Python reports death-by-signal as -N; shells report 128+N.
    return 128 - returncode if returncode < 0 else returncode
