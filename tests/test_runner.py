import io
import os
import pty
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from squeeze import runner

PROJECT = Path(__file__).resolve().parent.parent
# A throwaway home keeps test runs out of the real ~/.squeeze/history.jsonl.
_HOME = tempfile.TemporaryDirectory()
ENV = {**os.environ, "PYTHONPATH": str(PROJECT), "HOME": _HOME.name}
SQ = [sys.executable, "-m", "squeeze.cli"]


def py(code):
    return [sys.executable, "-c", code]


class SqTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()

    def sq(self, *argv):
        return subprocess.run([*SQ, *argv], cwd=self.dir, env=ENV, capture_output=True, stdin=subprocess.DEVNULL)

    def logs(self, root=None):
        return sorted((root or self.dir).glob(".squeeze/logs/*.log"))

    def test_exit_codes_are_preserved(self):
        for code in (0, 1, 3, 255):
            self.assertEqual(self.sq(*py(f"raise SystemExit({code})")).returncode, code)

    def test_death_by_signal_uses_shell_convention(self):
        result = self.sq(*py("import os, signal; os.kill(os.getpid(), signal.SIGKILL)"))
        self.assertEqual(result.returncode, 128 + signal.SIGKILL)

    def test_missing_command_is_127_and_logged(self):
        result = self.sq("definitely-not-a-command")
        self.assertEqual(result.returncode, 127)
        self.assertIn(b"command not found", result.stdout)
        self.assertIn(b"command not found", self.logs()[0].read_bytes())

    def test_not_executable_is_126(self):
        script = self.dir / "script"
        script.write_text("#!/bin/sh\n")
        self.assertEqual(self.sq(str(script)).returncode, 126)

    def test_log_has_both_streams_in_order(self):
        code = "import sys\nfor s in (sys.stdout, sys.stderr, sys.stdout): print(s.name, file=s, flush=True)"
        result = self.sq(*py(code))
        expected = b"<stdout>\n<stderr>\n<stdout>\n"
        self.assertEqual(self.logs()[0].read_bytes(), expected)
        self.assertIn(expected, result.stdout)

    def test_binary_output_survives(self):
        result = self.sq(*py(r"import sys; sys.stdout.buffer.write(b'\xff\xfe')"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.logs()[0].read_bytes(), b"\xff\xfe")

    def test_runs_in_the_same_second_keep_separate_logs(self):
        for _ in range(3):
            self.sq("true")
        self.assertEqual(len(self.logs()), 3)

    def test_log_goes_to_repo_root_from_a_subdirectory(self):
        (self.dir / ".git").mkdir()
        sub = self.dir / "a" / "b"
        sub.mkdir(parents=True)
        subprocess.run([*SQ, "true"], cwd=sub, env=ENV, capture_output=True)
        self.assertEqual(len(self.logs()), 1)

    def test_gitignore_updated_once_and_only_in_a_repo(self):
        self.sq("true")
        self.assertFalse((self.dir / ".gitignore").exists())

        (self.dir / ".git").mkdir()
        (self.dir / ".gitignore").write_text("node_modules/")  # no trailing newline
        self.assertIn(b"added .squeeze/", self.sq("true").stderr)
        self.assertNotIn(b"added .squeeze/", self.sq("true").stderr)
        self.assertEqual((self.dir / ".gitignore").read_text(), "node_modules/\n.squeeze/\n")

    def test_unwritable_log_dir_fails_loudly(self):
        (self.dir / ".squeeze").write_text("a file where the directory should be")
        result = self.sq("true")
        self.assertEqual(result.returncode, 125)
        self.assertIn(b"command not run", result.stderr)

    def test_no_arguments_is_a_usage_error(self):
        self.assertEqual(self.sq().returncode, 2)

    def test_signals_reach_the_child_and_partial_log_is_kept(self):
        child = py("import time; print('started', flush=True); time.sleep(30); print('fin' + 'ished')")
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(sig=sig):
                # A new session has no terminal, so this signal is sq's alone to pass on.
                proc = subprocess.Popen(
                    [*SQ, *child], cwd=self.dir, env=ENV, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                )
                self.addCleanup(proc.kill)
                self.addCleanup(proc.stdout.close)
                before = set(self.logs())
                log = self.wait_for_started_log(before)
                proc.send_signal(sig)
                self.assertEqual(proc.wait(timeout=10), 128 + sig)
                self.assertNotIn(b"finished", log.read_bytes())

    def test_piped_stdin_reaches_the_command(self):
        result = subprocess.run(
            [*SQ, "cat"], cwd=self.dir, env=ENV, capture_output=True, input=b"from the pipe\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"from the pipe", result.stdout)

    def run_in_terminal(self, child, *, piped_stdin=False, ctrl_c=True):
        """Run sq in a real pseudo-terminal. Returns (exit code, log text)."""
        before = set(self.logs())
        pipe_read, pipe_write = os.pipe()
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.dir)
            if piped_stdin:
                os.dup2(pipe_read, 0)
            os.execve(sys.executable, [sys.executable, *SQ[1:], *child], ENV)
        os.close(pipe_read)
        self.addCleanup(os.close, pipe_write)
        self.addCleanup(os.close, fd)
        if ctrl_c:
            self.wait_for_started_log(before)
            os.write(fd, b"\x03")
        # A pty's output has to be drained or the writer can block.
        try:
            while os.read(fd, 4096):
                pass
        except OSError:
            pass
        _, status = os.waitpid(pid, 0)
        log = (set(self.logs()) - before).pop()
        return os.waitstatus_to_exitcode(status), log.read_text()

    COUNTS_SIGINTS = (
        "import signal, sys, time\n"
        "seen = [0]\n"
        "def handler(*_):\n"
        "    seen[0] += 1\n"
        "    print('sigint', seen[0], flush=True)\n"
        "signal.signal(signal.SIGINT, handler)\n"
        "print('started', flush=True)\n"
        "time.sleep(1)\n"
        "sys.exit(7)\n"
    )

    def test_ctrl_c_at_a_terminal_reaches_the_child_once(self):
        for piped_stdin in (False, True):
            with self.subTest(piped_stdin=piped_stdin):
                code, log = self.run_in_terminal(py(self.COUNTS_SIGINTS), piped_stdin=piped_stdin)
                self.assertEqual(code, 7)
                self.assertEqual(log.count("sigint"), 1)

    def test_ctrl_c_in_raw_mode_reaches_the_child_once(self):
        code, log = self.run_in_terminal(["--raw", *py(self.COUNTS_SIGINTS)])
        self.assertEqual(code, 7)
        self.assertEqual(log.count("sigint"), 1)

    def test_a_prompt_at_a_terminal_fails_instead_of_hanging(self):
        code, log = self.run_in_terminal(py("input('Continue? ')"), ctrl_c=False)
        self.assertEqual(code, 1)
        self.assertIn("EOFError", log)

    def test_silence_gets_one_notice(self):
        log_path = self.dir / "quiet.log"
        stderr = io.StringIO()
        with log_path.open("xb") as log_file, mock.patch.object(runner, "STALL_NOTICE_SECONDS", 0.1), \
                mock.patch.object(sys, "stderr", stderr):
            code = runner.run(py("import time; time.sleep(0.5)"), log_file)
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue().count("may be waiting for input"), 1)

    def test_steady_output_gets_no_notice(self):
        log_path = self.dir / "busy.log"
        stderr = io.StringIO()
        child = py("import time\nfor _ in range(10):\n    print('x', flush=True)\n    time.sleep(0.05)")
        with log_path.open("xb") as log_file, mock.patch.object(runner, "STALL_NOTICE_SECONDS", 0.2), \
                mock.patch.object(sys, "stderr", stderr):
            runner.run(child, log_file)
        self.assertEqual(stderr.getvalue(), "")

    def wait_for_started_log(self, before):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for log in set(self.logs()) - before:
                if b"started" in log.read_bytes():
                    return log
            time.sleep(0.05)
        self.fail("child never started")


if __name__ == "__main__":
    unittest.main()
