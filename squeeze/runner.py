"""Run a command with its output going to a log file."""
import os
import selectors
import signal
import subprocess
import sys
import time

STALL_NOTICE_SECONDS = 30
SPINNER_DELAY_SECONDS = 1  # a quick command shouldn't flicker
SPINNER_TICK_SECONDS = 0.1
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
MAX_LABEL = 40
CLEAR_LINE = "\r\x1b[K"


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


def _wants_spinner():
    """Only for a person at a terminal: to an agent or a log, a spinner is just tokens."""
    return sys.stderr.isatty() and os.environ.get("TERM") != "dumb" and not os.environ.get("CI")


def _wait(proc, log_file, label):
    """Wait for proc, whose output is going to the log. Show it's alive, and say once if it goes quiet: it may want input."""
    spinner = _wants_spinner()
    started = last_output = time.monotonic()
    size = 0
    noted = False
    drawn = False
    ticks = 0
    try:
        while True:
            try:
                return proc.wait(timeout=SPINNER_TICK_SECONDS if spinner else STALL_NOTICE_SECONDS)
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                current = os.fstat(log_file.fileno()).st_size
                if current != size:
                    size = current
                    last_output = now
                if now - last_output >= STALL_NOTICE_SECONDS and not noted:
                    noted = True
                    print(f"{CLEAR_LINE if drawn else ''}sq: still running, no output for {STALL_NOTICE_SECONDS}s, it may be waiting for input (log: {log_file.name})", file=sys.stderr)
                if spinner and now - started >= SPINNER_DELAY_SECONDS:
                    drawn = True
                    ticks += 1
                    frame = SPINNER_FRAMES[ticks % len(SPINNER_FRAMES)]
                    sys.stderr.write(f"{CLEAR_LINE}{frame} {label[:MAX_LABEL]} · {now - started:.0f}s")
                    sys.stderr.flush()
    finally:
        if drawn:
            sys.stderr.write(CLEAR_LINE)
            sys.stderr.flush()


def _write_all(fd, data):
    while data:
        data = data[os.write(fd, data):]


def _tee(proc, log_file):
    """Copy the command's output to the screen and the log as it arrives, keeping stdout and stderr apart."""
    log_ok = True
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout.fileno(), selectors.EVENT_READ, 1)
        selector.register(proc.stderr.fileno(), selectors.EVENT_READ, 2)
        while selector.get_map():
            events = selector.select(timeout=0.1)
            for key, _ in events:
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fd)
                    continue
                try:
                    if log_ok:
                        log_file.write(data)
                        log_file.flush()
                except OSError as e:
                    # A full disk shouldn't stop a command the user is watching.
                    log_ok = False
                    print(f"sq: log writing stopped: {e}", file=sys.stderr)
                try:
                    _write_all(key.data, data)
                except BrokenPipeError:
                    # `sq --raw cmd | head` closed. Unwrapped, cmd would get SIGPIPE from the same write.
                    proc.send_signal(signal.SIGPIPE)
                except OSError:
                    pass
            # A daemon the command left behind can hold the pipes open forever.
            if not events and proc.poll() is not None:
                break
    proc.stdout.close()
    proc.stderr.close()
    return proc.wait()


def run(argv, log_file, raw=False, label=None):
    """Run argv, saving its output to log_file. Returns a shell-style exit code.

    Normally the output only goes to the log. With raw it also streams to the screen as usual.
    """
    proc = None

    def forward(signum, _frame):
        # Sending a terminal's Ctrl+C a second time makes many tools force-quit.
        if proc and (signum == signal.SIGTERM or not _terminal_sent_it()):
            proc.send_signal(signum)

    def could_not_start(code, message):
        log_file.write(f"{message}\n".encode())
        if raw:
            print(message, file=sys.stderr)
        return code

    previous = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        try:
            if raw:
                # Prompts are visible here, so stdin stays connected.
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                # The child writes straight to the file: both streams stay in order, a
                # partial log survives any interruption, and a daemon the command leaves
                # behind can't hang us the way it would by holding a pipe open.
                # Nobody can see a prompt in the log, so a terminal's stdin would only hang
                # the command. With no input it fails fast instead. Piped stdin still works.
                stdin = subprocess.DEVNULL if os.isatty(0) else None
                proc = subprocess.Popen(argv, stdin=stdin, stdout=log_file, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            return could_not_start(127, f"sq: command not found: {argv[0]}")
        except OSError as e:
            return could_not_start(126, f"sq: cannot run {argv[0]}: {e}")
        returncode = _tee(proc, log_file) if raw else _wait(proc, log_file, label or argv[0])
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)

    # Python reports death-by-signal as -N; shells report 128+N.
    return 128 - returncode if returncode < 0 else returncode
