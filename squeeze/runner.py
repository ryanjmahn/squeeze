"""Run a command with all of its output going to a log file."""
import os
import signal
import subprocess
import sys

STALL_NOTICE_SECONDS = 30


def _terminal_sent_it():
    """A terminal's Ctrl+C goes to its whole foreground process group, so the child already has it."""
    try:
        tty = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        return False
    try:
        return os.tcgetpgrp(tty) == os.getpgrp()
    except OSError:
        return False
    finally:
        os.close(tty)


def _wait(proc, log_file):
    """Wait for proc. Its output goes to the log, so say once if it goes quiet: it may want input."""
    size = 0
    noted = False
    while True:
        try:
            return proc.wait(timeout=STALL_NOTICE_SECONDS)
        except subprocess.TimeoutExpired:
            current = os.fstat(log_file.fileno()).st_size
            if current == size and not noted:
                noted = True
                print(f"sq: still running, no output for {STALL_NOTICE_SECONDS}s, it may be waiting for input (log: {log_file.name})", file=sys.stderr)
            size = current


def run(argv, log_file):
    """Run argv, writing stdout and stderr to log_file. Returns a shell-style exit code."""
    proc = None

    def forward(signum, _frame):
        # Sending a terminal's Ctrl+C a second time makes many tools force-quit.
        if proc and (signum == signal.SIGTERM or not _terminal_sent_it()):
            proc.send_signal(signum)

    previous = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        # The child writes straight to the file: both streams stay in order, a
        # partial log survives any interruption, and a daemon the command leaves
        # behind can't hang us the way it would by holding a pipe open.
        # Nobody can see a prompt in the log, so a terminal's stdin would only hang
        # the command. With no input it fails fast instead. Piped stdin still works.
        stdin = subprocess.DEVNULL if os.isatty(0) else None
        proc = subprocess.Popen(argv, stdin=stdin, stdout=log_file, stderr=subprocess.STDOUT)
        returncode = _wait(proc, log_file)
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
