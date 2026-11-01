import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from squeeze import cli, logs

PROJECT = Path(__file__).resolve().parent.parent
SQ = [sys.executable, "-m", "squeeze.cli"]


class CliTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve() / "my-repo"
        self.dir.mkdir()
        self.home = Path(tmp.name).resolve() / "home"
        self.home.mkdir()
        self.env = {**os.environ, "PYTHONPATH": str(PROJECT), "HOME": str(self.home)}
        self.env.pop("SQUEEZE_KEEP_LOGS", None)

    def sq(self, *argv, **kwargs):
        options = {"cwd": self.dir, "env": self.env, "capture_output": True, "stdin": subprocess.DEVNULL, "timeout": 30}
        return subprocess.run([*SQ, *argv], **{**options, **kwargs})

    def logs(self):
        return sorted(self.dir.glob(".squeeze/logs/*.log"))

    def history(self):
        path = self.home / ".squeeze" / "history.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]


class ShortOutputTest(CliTestCase):
    def test_nothing_hidden_means_no_stats_or_log_path(self):
        result = self.sq("sh", "-c", "echo hi")
        self.assertRegex(result.stdout.decode().split("🎖")[0], r"^🍋 sh · exit 0 · [\d.]+s\nhi\n$")

    def test_silent_success_is_one_line(self):
        self.sq("true")  # the first run earns a badge
        self.assertRegex(self.sq("true").stdout.decode(), r"^🍋 true · exit 0 · [\d.]+s\n$")

    def test_a_short_failure_still_shows_its_exit_code_and_output(self):
        self.sq("true")
        result = self.sq("sh", "-c", "echo broke; exit 3")
        self.assertEqual(result.returncode, 3)
        self.assertRegex(result.stdout.decode(), r"^🍋 sh · exit 3 · [\d.]+s\nbroke\n$")

    def test_the_log_is_still_saved(self):
        self.sq("sh", "-c", "echo hi")
        self.assertEqual(self.logs()[0].read_text(), "hi\n")

    def test_long_output_keeps_the_full_report(self):
        text = self.sq("sh", "-c", "seq 1000").stdout.decode()
        self.assertIn("1000 lines →", text)
        self.assertIn("full log: ", text)

    def test_a_shortened_line_points_to_the_log(self):
        code = "print('x' * 5000)"
        self.assertIn("full log: ", self.sq(sys.executable, "-c", code).stdout.decode())

    def test_history_records_what_was_really_printed(self):
        self.sq("true")
        result = self.sq("true")
        entry = self.history()[1]
        self.assertEqual(entry["lines_after"], 1)
        self.assertEqual(entry["tokens_after"], len(result.stdout.decode()) // 4)


class InitTest(CliTestCase):
    def test_prints_only_the_snippet_to_stdout(self):
        result = self.sq("init")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), cli.CLAUDE_SNIPPET)
        self.assertTrue(cli.CLAUDE_SNIPPET.startswith("## Squeeze (noisy commands)\n"))
        self.assertIn(b"CLAUDE.md", result.stderr)

    def test_creates_no_logs_or_history(self):
        self.sq("init")
        self.assertEqual(self.logs(), [])
        self.assertFalse((self.home / ".squeeze").exists())

    def test_a_real_command_named_init_is_reachable(self):
        self.assertEqual(self.sq("--", "init").returncode, 127)


class ArgumentsTest(CliTestCase):
    def test_flags_after_the_command_belong_to_the_command(self):
        result = self.sq("sh", "-c", 'echo "got $1"', "sh", "--raw")
        self.assertIn(b"got --raw", result.stdout)
        self.assertIn(b"exit 0", result.stdout.split(b"\n")[0])  # sq's header, so sq didn't take the flag

    def test_help_after_the_command_belongs_to_the_command(self):
        self.assertIn(b"got -h", self.sq("sh", "-c", 'echo "got $1"', "sh", "-h").stdout)

    def test_unknown_flags_are_a_usage_error(self):
        result = self.sq("--nope", "true")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.logs(), [])

    def test_no_command_is_a_usage_error(self):
        for argv in ([], ["--raw"]):
            with self.subTest(argv):
                self.assertEqual(self.sq(*argv).returncode, 2)

    def test_s_and_a_command_together_are_a_usage_error(self):
        result = self.sq("-s", "true", "false")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"not both", result.stderr)

    def test_s_needs_a_value(self):
        self.assertEqual(self.sq("-s").returncode, 2)

    def test_help_works(self):
        result = self.sq("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"--raw", result.stdout)


class ShellTest(CliTestCase):
    def test_pipes_and_chains_run_in_a_shell(self):
        result = self.sq("-s", "echo one | tr a-z A-Z && echo two")
        self.assertIn(b"ONE\ntwo", result.stdout)

    def test_exit_code_is_the_shells(self):
        self.assertEqual(self.sq("-s", "true && exit 7").returncode, 7)
        self.assertEqual(self.sq("-s", "false || exit 8").returncode, 8)

    def test_arguments_are_not_shell_parsed_without_s(self):
        result = self.sq("echo", "$HOME && echo injected")
        self.assertIn(b"$HOME && echo injected", result.stdout)

    def test_named_after_its_first_word(self):
        result = self.sq("-s", "echo hi && echo there")
        self.assertTrue(result.stdout.startswith("🍋 echo · ".encode()))
        self.assertTrue(self.logs()[0].name.endswith("_echo.log"))

    def test_env_assignments_are_not_the_command(self):
        self.assertEqual(cli._shell_words("CI=1 API_KEY=hunter2 npm install"), ["npm", "install"])

    def test_a_secret_assignment_goes_nowhere_but_the_shell(self):
        result = self.sq("-s", "API_KEY=hunter2 echo hi")
        self.assertIn("🍋 echo · ".encode(), result.stdout)
        self.assertNotIn("hunter2", self.logs()[0].name)
        self.assertNotIn("hunter2", json.dumps(self.history()))

    def test_only_assignments_is_named_sh(self):
        result = self.sq("-s", "A=1")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.logs()[0].name.endswith("_sh.log"))


class RawTest(CliTestCase):
    def test_output_is_not_squeezed_and_the_log_is_saved(self):
        result = self.sq("--raw", "sh", "-c", "seq 1000; exit 3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(len(result.stdout.splitlines()), 1000)
        self.assertEqual(len(self.logs()[0].read_text().splitlines()), 1000)

    def test_stdout_and_stderr_stay_separate(self):
        result = self.sq("--raw", "sh", "-c", "echo to-out; echo to-err >&2")
        self.assertEqual(result.stdout, b"to-out\n")
        self.assertIn(b"to-err\n", result.stderr)
        log = self.logs()[0].read_bytes()
        self.assertIn(b"to-out", log)
        self.assertIn(b"to-err", log)

    def test_the_footer_goes_to_stderr(self):
        result = self.sq("--raw", "true")
        self.assertEqual(result.stdout, b"")
        self.assertRegex(result.stderr.decode(), r"🍋 true · exit 0 · [\d.]+s · raw · full log: \.squeeze/logs/")

    def test_output_arrives_while_the_command_runs(self):
        proc = subprocess.Popen(
            [*SQ, "--raw", sys.executable, "-c", "import time; print('early', flush=True); time.sleep(30)"],
            cwd=self.dir, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        self.assertEqual(proc.stdout.readline(), b"early\n")

    def test_stdin_stays_connected(self):
        result = self.sq("--raw", "cat", input=b"typed\n", stdin=None)
        self.assertEqual(result.stdout, b"typed\n")

    def test_missing_command_is_reported(self):
        result = self.sq("--raw", "definitely-not-a-command")
        self.assertEqual(result.returncode, 127)
        self.assertIn(b"command not found", result.stderr)
        self.assertIn(b"command not found", self.logs()[0].read_bytes())

    def test_a_daemon_left_behind_does_not_hang_it(self):
        started = time.monotonic()
        result = self.sq("--raw", "sh", "-c", "sleep 20 & echo hi", timeout=15)
        self.assertEqual(result.stdout, b"hi\n")
        self.assertLess(time.monotonic() - started, 10)

    def test_a_closed_reader_stops_the_command(self):
        # Without SIGPIPE this would run forever.
        command = f'{sys.executable} -m squeeze.cli --raw yes | head -1'
        result = subprocess.run(command, shell=True, cwd=self.dir, env=self.env, capture_output=True, timeout=15)
        self.assertEqual(result.stdout, b"y\n")

    def test_works_with_s(self):
        result = self.sq("--raw", "-s", "echo a | tr a b; exit 4")
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stdout, b"b\n")

    def test_recorded_as_saving_nothing(self):
        self.sq("--raw", "sh", "-c", "seq 100")
        entry = self.history()[0]
        self.assertTrue(entry["raw"])
        self.assertEqual(entry["lines_before"], 100)
        self.assertEqual(entry["lines_after"], 100)
        self.assertEqual(entry["tokens_before"], entry["tokens_after"])


class RotationTest(CliTestCase):
    def make_logs(self, count):
        log_dir = self.dir / ".squeeze" / "logs"
        log_dir.mkdir(parents=True)
        for n in range(count):
            path = log_dir / f"old-{n:03}.log"
            path.write_text("x")
            os.utime(path, (1000 + n, 1000 + n))

    def test_default_keeps_50(self):
        self.make_logs(60)
        self.sq("true")
        logs = self.logs()
        self.assertEqual(len(logs), 50)
        names = [path.name for path in logs]
        self.assertNotIn("old-010.log", names)
        self.assertIn("old-011.log", names)
        self.assertIn("old-059.log", names)

    def test_the_limit_can_be_changed(self):
        self.make_logs(10)
        self.sq("true", env={**self.env, "SQUEEZE_KEEP_LOGS": "3"})
        self.assertEqual(len(self.logs()), 3)

    def test_a_bad_limit_means_the_default(self):
        for value in ("nope", "0", "-5", ""):
            with self.subTest(value):
                self.assertEqual(self.sq("true", env={**self.env, "SQUEEZE_KEEP_LOGS": value}).returncode, 0)
        self.assertEqual(len(self.logs()), 4)

    def test_the_current_log_always_survives(self):
        # A long command's log can be older than a hundred newer ones by the time it ends.
        self.make_logs(5)
        for path in self.logs():
            os.utime(path, (4_000_000_000, 4_000_000_000))
        result = self.sq("sh", "-c", "seq 1000", env={**self.env, "SQUEEZE_KEEP_LOGS": "1"})
        printed = result.stdout.decode().split("full log: ")[1].split("\n")[0]
        self.assertTrue((self.dir / printed).exists())

    def test_other_files_are_left_alone(self):
        self.make_logs(5)
        keep = self.dir / ".squeeze" / "logs" / "notes.txt"
        keep.write_text("mine")
        self.sq("true", env={**self.env, "SQUEEZE_KEEP_LOGS": "1"})
        self.assertTrue(keep.exists())

    def test_rotation_failure_keeps_the_exit_code(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dir)
        stderr = io.StringIO()
        with mock.patch.object(logs, "rotate", side_effect=PermissionError("nope")), \
                mock.patch.object(sys, "stdout", io.TextIOWrapper(io.BytesIO())), \
                mock.patch.object(sys, "stderr", stderr), mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            code = cli.main(["sh", "-c", "exit 6"])
        self.assertEqual(code, 6)
        self.assertIn("could not remove old logs", stderr.getvalue())


class HistoryTest(CliTestCase):
    def test_a_run_is_recorded(self):
        result = self.sq("sh", "-c", "seq 1000; exit 3")
        entry = self.history()[0]
        self.assertEqual(entry["v"], 1)
        self.assertEqual(entry["repo"], "my-repo")
        self.assertEqual(entry["command"], "sh")
        self.assertEqual(entry["tool"], "generic")
        self.assertEqual(entry["exit"], 3)
        self.assertFalse(entry["raw"])
        self.assertEqual(entry["lines_before"], 1000)
        self.assertEqual(entry["lines_after"], len(result.stdout.splitlines()))
        self.assertEqual(entry["tokens_after"], len(result.stdout.decode()) // 4)
        self.assertGreater(entry["tokens_before"], entry["tokens_after"])
        self.assertGreaterEqual(entry["seconds"], 0)

    def test_the_timestamp_knows_its_timezone(self):
        self.sq("true")
        self.assertIsNotNone(datetime.fromisoformat(self.history()[0]["ts"]).utcoffset())

    def test_runs_append(self):
        for _ in range(3):
            self.sq("true")
        self.assertEqual(len(self.history()), 3)

    def test_the_tool_is_the_squeezer_that_handled_it(self):
        code = "print('=== test session starts ==='); print('=== 3 passed in 0.1s ===')"
        self.sq(sys.executable, "-c", code)
        self.assertEqual(self.history()[0]["tool"], "pytest")

    def test_failed_starts_are_recorded(self):
        self.sq("definitely-not-a-command")
        self.assertEqual(self.history()[0]["exit"], 127)

    def test_arguments_and_output_are_never_stored(self):
        self.sq("sh", "-c", "echo OUTPUT_SECRET", "--token=ARG_SECRET")
        self.sq("-s", "echo SHELL_SECRET")
        text = (self.home / ".squeeze" / "history.jsonl").read_text()
        for secret in ("OUTPUT_SECRET", "ARG_SECRET", "SHELL_SECRET"):
            self.assertNotIn(secret, text)

    def test_only_the_command_name_is_stored_not_its_path(self):
        self.sq("/bin/sh", "-c", "true")
        self.assertEqual(self.history()[0]["command"], "sh")

    def test_the_file_is_private(self):
        self.sq("true")
        path = self.home / ".squeeze" / "history.jsonl"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_an_unwritable_history_keeps_the_exit_code(self):
        (self.home / ".squeeze").write_text("a file where the directory should be")
        result = self.sq("sh", "-c", "echo fine; exit 6")
        self.assertEqual(result.returncode, 6)
        self.assertIn(b"fine", result.stdout)
        self.assertIn(b"could not update history", result.stderr)

    def test_parallel_runs_do_not_corrupt_it(self):
        procs = [
            subprocess.Popen([*SQ, "true"], cwd=self.dir, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            for _ in range(12)
        ]
        for proc in procs:
            proc.wait()
        self.assertEqual(len(self.history()), 12)


if __name__ == "__main__":
    unittest.main()
