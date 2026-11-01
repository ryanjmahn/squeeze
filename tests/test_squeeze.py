import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from squeeze import cli, squeezers, stats
from squeeze.clean import clean, collapse_runs, render_run
from squeeze.squeezers import generic

PROJECT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "PYTHONPATH": str(PROJECT)}


def collapse(*lines):
    return [render_run(*run) for run in collapse_runs(lines)]


class CleanTest(unittest.TestCase):
    def test_strips_colors_cursor_moves_and_links(self):
        raw = "\x1b[31;1mred\x1b[0m \x1b[2Kcleared \x1b]8;;http://x\x07link\x1b]8;;\x07"
        self.assertEqual(clean(raw), "red cleared link")

    def test_progress_bars_keep_only_the_final_state(self):
        self.assertEqual(clean("10%\r50%\r100%\ndone\n"), "100%\ndone")

    def test_windows_line_endings(self):
        self.assertEqual(clean("one\r\ntwo\r\n"), "one\ntwo")


class CollapseTest(unittest.TestCase):
    def test_identical_lines_get_a_count(self):
        self.assertEqual(collapse(*["warning: old"] * 37), ["(× 37) warning: old"])

    def test_near_identical_lines_keep_the_newest(self):
        self.assertEqual(collapse("Downloading 1%", "Downloading 50%", "Downloading 100%"), ["(× 3) Downloading 100%"])

    def test_errors_differing_by_a_number_stay_separate(self):
        lines = ["a.py:10: error: bad", "a.py:20: error: bad"]
        self.assertEqual(collapse(*lines), lines)

    def test_identical_errors_do_collapse(self):
        self.assertEqual(collapse("error: bad", "error: bad"), ["(× 2) error: bad"])

    def test_only_consecutive_lines_collapse(self):
        self.assertEqual(collapse("a", "b", "a"), ["a", "b", "a"])

    def test_blank_runs_become_one_blank_without_a_count(self):
        self.assertEqual(collapse("a", "", "  ", "", "b"), ["a", "", "b"])


class GenericTest(unittest.TestCase):
    def noise(self, n, prefix="noise"):
        return [f"{prefix} {chr(97 + i % 26)}{chr(97 + i // 26 % 26)}" for i in range(n)]

    def test_short_output_is_untouched(self):
        output = "\n".join(self.noise(10))
        self.assertEqual(generic.squeeze(output, 0), output)

    def test_keeps_head_tail_and_error_with_context(self):
        lines = self.noise(500)
        lines[250:253] = ["before it", "FATAL: disk full", "after it"]
        result = generic.squeeze("\n".join(lines), 1).split("\n")
        self.assertEqual(result[:3], lines[:3])
        self.assertEqual(result[-20:], lines[-20:])
        for line in lines[250:253]:
            self.assertIn(line, result)
        self.assertLess(len(result), 40)

    def test_error_match_ignores_case(self):
        for word in ("error", "Failed", "EXCEPTION", "fatal"):
            lines = self.noise(500)
            lines[250] = f"something {word} here"
            self.assertIn(lines[250], generic.squeeze("\n".join(lines), 1))

    def test_every_distinct_error_survives_on_success_too(self):
        lines = self.noise(500)
        errors = [f"src/a.py:{n}: error: bad" for n in range(100, 110)]
        lines[100:100] = errors
        result = generic.squeeze("\n".join(lines), 0)
        for error in errors:
            self.assertIn(error, result)

    def test_success_keeps_a_shorter_tail_than_failure(self):
        output = "\n".join(self.noise(500))
        self.assertLess(len(generic.squeeze(output, 0)), len(generic.squeeze(output, 1)))

    def test_repeated_error_elsewhere_is_shown_once(self):
        lines = self.noise(500)
        lines[100] = lines[300] = "Error: same thing"
        self.assertEqual(generic.squeeze("\n".join(lines), 1).count("Error: same thing"), 1)

    def test_hidden_notes_account_for_every_line(self):
        lines = self.noise(500)
        lines[100:100] = ["repeat"] * 40
        lines[300] = "Error: boom"
        result = generic.squeeze("\n".join(lines), 1)
        hidden = sum(int(n) for n in re.findall(r"… (\d+) lines hidden …", result))
        counted = sum(
            int(m[1]) if (m := re.match(r"\(× (\d+)\)", line)) else 1
            for line in result.split("\n")
            if "hidden" not in line
        )
        self.assertEqual(hidden + counted, len(lines))

    def test_small_gaps_are_shown_not_noted(self):
        output = "\n".join(self.noise(10 + generic.TAIL_ON_SUCCESS))
        lines = output.split("\n")
        two_hidden = "\n".join(lines[: generic.HEAD + 2] + lines[-generic.TAIL_ON_SUCCESS :])
        self.assertEqual(generic.squeeze(two_hidden, 0), two_hidden)


class Crashes:
    @staticmethod
    def matches(command, output):
        return True

    @staticmethod
    def squeeze(output, exit_code):
        raise ValueError("bug")


class ReturnsNothing(Crashes):
    @staticmethod
    def squeeze(output, exit_code):
        return ""


class FallbackTest(unittest.TestCase):
    RAW = "FAILED: the important thing\n"

    def result_with(self, *fakes):
        with mock.patch.object(squeezers, "SQUEEZERS", list(fakes)):
            return squeezers.squeeze(["tool"], self.RAW, 1)

    def test_crashing_squeezer_falls_back_to_generic(self):
        self.assertIn("the important thing", self.result_with(Crashes))

    def test_empty_result_falls_back_to_generic(self):
        self.assertIn("the important thing", self.result_with(ReturnsNothing))

    def test_crashing_generic_falls_back_to_raw(self):
        with mock.patch.object(generic, "squeeze", side_effect=ValueError("bug")):
            self.assertEqual(self.result_with(Crashes), self.RAW)

    def test_crashing_clean_falls_back_to_raw(self):
        with mock.patch.object(squeezers, "clean", side_effect=ValueError("bug")):
            self.assertEqual(self.result_with(), self.RAW)


class StatsTest(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(
            stats.summary("x\n" * 812, "y\n" * 19 + "z" * 4000),
            "812 lines → 20 lines (-97%) · ~406 → ~1.0k tokens (est.)",
        )

    def test_nothing_saved_shows_no_percentage(self):
        self.assertEqual(stats.summary("", ""), "0 lines → 0 lines · ~0 → ~0 tokens (est.)")

    def test_percentage_never_rounds_up_to_100(self):
        self.assertIn("(-99%)", stats.summary("x\n" * 1000, "y\n" * 2))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()

    def test_noisy_failure(self):
        code = (
            "import sys\n"
            "for i in range(2000): print(f'\\x1b[32mstep {chr(97 + i % 26)} {i}\\x1b[0m')\n"
            "print('AssertionError: the real problem')\n"
            "sys.exit(3)\n"
        )
        result = subprocess.run(
            [sys.executable, "-m", "squeeze.cli", sys.executable, "-c", code],
            cwd=self.dir, env=ENV, capture_output=True,
        )
        text = result.stdout.decode()
        self.assertEqual(result.returncode, 3)
        self.assertIn("AssertionError: the real problem", text)
        self.assertRegex(text, r"exit 3 · .*2001 lines → \d+ lines \(-\d+%\) · ~.* tokens \(est\.\)")
        self.assertRegex(text, r"lines hidden")
        self.assertNotIn("\x1b", text)
        self.assertLess(len(text.splitlines()), 50)
        log = next(self.dir.glob(".squeeze/logs/*.log")).read_text()
        self.assertEqual(len(log.splitlines()), 2001)
        self.assertIn("\x1b[32m", log)

    def test_broken_squeezing_still_prints_the_log_and_keeps_the_exit_code(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dir)
        stdout = io.TextIOWrapper(io.BytesIO())
        with mock.patch.object(squeezers, "squeeze", side_effect=RuntimeError("bug")), \
                mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", io.StringIO()):
            code = cli.main(["sh", "-c", "echo the output; exit 9"])
        self.assertEqual(code, 9)
        self.assertEqual(stdout.buffer.getvalue(), b"the output\n")


if __name__ == "__main__":
    unittest.main()
