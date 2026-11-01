"""Fixtures are real pytest output, with only absolute temp paths rewritten."""
import re
import unittest
from pathlib import Path

from squeeze import squeezers
from squeeze.squeezers import generic, pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Fixture name → the exit code pytest really returned when it was captured.
EXIT_CODES = {
    "pytest_failures": 1,
    "pytest_failures_verbose": 1,
    "pytest_failures_quiet": 1,
    "pytest_failures_tb_short": 1,
    "pytest_failures_tb_native": 1,
    "pytest_failures_tb_line": 1,
    "pytest_failures_tb_no": 1,
    "pytest_stop_early": 1,
    "pytest_edge_cases": 1,
    "pytest_fake_section": 1,
    "pytest_keyboard_interrupt": 2,
    "pytest_subtests_failed": 1,
    "pytest_subtests_passed": 0,
    "pytest_cov_with_failures": 1,
    "pytest_cov_threshold_only": 1,
    "pytest_cov_passing": 0,
    "pytest_v8_failures": 1,
    "pytest_v8_passed": 0,
    "pytest_all_passed": 0,
    "pytest_collection_error": 2,
    "pytest_collection_import_error": 2,
    "pytest_no_tests": 5,
    "pytest_usage_error": 4,
}


def load(name):
    return (FIXTURES / f"{name}.txt").read_text()


def run(name, exit_code=None):
    """The full path a real run takes, including every fallback."""
    return squeezers.squeeze(["pytest"], load(name), EXIT_CODES[name] if exit_code is None else exit_code)


def direct(name):
    return pytest.squeeze(squeezers.clean(load(name)), EXIT_CODES[name])


class EveryFixtureTest(unittest.TestCase):
    def test_no_failure_is_ever_dropped(self):
        for name in EXIT_CODES:
            with self.subTest(name):
                result = run(name)
                for failed in re.findall(r"^(?:FAILED|ERROR) (\S+)", load(name), re.MULTILINE):
                    self.assertIn(failed, result)

    def test_only_a_real_pass_gets_a_checkmark(self):
        for name, code in EXIT_CODES.items():
            with self.subTest(name):
                self.assertEqual("✓" in run(name), code == 0)

    def test_output_gets_smaller(self):
        for name in EXIT_CODES:
            with self.subTest(name):
                self.assertLessEqual(len(run(name)), len(load(name)))


class ParsedFailuresTest(unittest.TestCase):
    def test_default_output(self):
        result = direct("pytest_failures")
        self.assertTrue(result.startswith("6 failed, 40 passed, 1 skipped, 1 xfailed, 40 warnings, 1 error in"))
        self.assertIn("✗ tests/test_auth.py::test_refresh_token\n", result)
        self.assertIn('auth/tokens.py:5  return token["expires_at"] + 1', result)
        self.assertIn("KeyError: 'expires_at'", result)
        self.assertIn("assert 429 == 200", result)
        self.assertIn("✗ tests/test_api.py::TestThing::test_method\n", result)
        self.assertIn("DID NOT RAISE ValueError", result)

    def test_exact_format_of_one_failure(self):
        for name in ("pytest_failures", "pytest_failures_tb_short"):
            with self.subTest(name):
                self.assertIn(
                    "✗ tests/test_auth.py::test_refresh_token\n"
                    '    tests/test_auth.py:6  assert refresh({"token": "abc"}) == 2\n'
                    '    auth/tokens.py:5  return token["expires_at"] + 1\n'
                    "    KeyError: 'expires_at'\n\n",
                    direct(name),
                )

    def test_diffs_keep_their_relative_indent(self):
        self.assertIn(
            "    AssertionError: assert 'a' == 'b'\n      - b\n      + a\n",
            direct("pytest_edge_cases"),
        )

    def test_is_much_smaller_than_the_original(self):
        for name in ("pytest_failures", "pytest_failures_verbose", "pytest_failures_quiet"):
            with self.subTest(name):
                self.assertLess(len(direct(name)), len(load(name)) / 3)

    def test_drops_passing_tests_and_source_listings(self):
        result = direct("pytest_failures_verbose")
        self.assertNotIn("PASSED", result)
        self.assertNotIn("test_passing_many", result)
        self.assertNotIn("is_simple", result)

    def test_frames_in_dependencies_are_dropped_but_their_errors_kept(self):
        result = direct("pytest_failures")
        self.assertNotIn("site-packages", result)
        self.assertNotIn("json/decoder.py", result)
        self.assertIn("auth/tokens.py:8  return Version(raw)", result)
        self.assertIn("InvalidVersion: Invalid version: 'not a version'", result)
        self.assertIn("JSONDecodeError: Expecting property name", result)

    def test_setup_errors_are_labelled(self):
        result = direct("pytest_failures")
        self.assertIn("✗ tests/test_api.py::test_uses_client (setup error)", result)
        self.assertIn("ConnectionError: database is down", result)

    def test_what_a_failing_test_printed_is_shown(self):
        self.assertIn(
            "    assert 429 == 200\n    Captured stdout call:\n      noise from the test\n",
            direct("pytest_failures"),
        )

    def test_long_captured_output_keeps_only_its_end(self):
        printed = "\n".join(f"print {n}" for n in range(100))
        output = (
            "=== FAILURES ===\n___ test_x ___\nE   assert False\n"
            f"--- Captured stdout call ---\n{printed}\n"
            "=== short test summary info ===\nFAILED a.py::test_x - assert False\n=== 1 failed in 0.1s ===\n"
        )
        result = pytest.squeeze(output, 1)
        self.assertIn("print 99", result)
        self.assertIn("95 earlier lines in the log", result)
        self.assertNotIn("print 50", result)

    def test_older_pytest_parses_the_same(self):
        result = direct("pytest_v8_failures")
        self.assertTrue(result.startswith("6 failed, 40 passed, 1 skipped, 1 xfailed, 40 warnings, 1 error in"))
        self.assertEqual(result.count("✗"), direct("pytest_failures").count("✗"))
        self.assertIn('auth/tokens.py:5  return token["expires_at"] + 1\n    KeyError: \'expires_at\'', result)
        self.assertRegex(direct("pytest_v8_passed"), r"^✓ 60 passed in [\d.]+s$")

    def test_warnings_become_one_line(self):
        self.assertIn(
            "⚠ 40 warnings (DeprecationWarning ×40 from utils/dates.py) — hidden",
            direct("pytest_failures"),
        )

    def test_short_tracebacks_parse_the_same(self):
        result = direct("pytest_failures_tb_short")
        self.assertIn('auth/tokens.py:5  return token["expires_at"] + 1', result)
        self.assertIn("KeyError: 'expires_at'", result)

    def test_formats_without_tracebacks_use_the_summary(self):
        for name in ("pytest_failures_tb_line", "pytest_failures_tb_no"):
            with self.subTest(name):
                self.assertIn("KeyError: 'expires_at'", direct(name))

    def test_native_tracebacks_are_parsed_too(self):
        result = direct("pytest_failures_tb_native")
        self.assertIn(
            "✗ tests/test_auth.py::test_refresh_token\n"
            '    tests/test_auth.py:6  assert refresh({"token": "abc"}) == 2\n'
            '    auth/tokens.py:5  return token["expires_at"] + 1\n'
            "    KeyError: 'expires_at'\n",
            result,
        )
        self.assertNotIn("site-packages", result)
        self.assertNotIn("pluggy", result)
        self.assertLess(len(result), len(load("pytest_failures_tb_native")) / 3)

    def test_failed_subtests_keep_their_path_and_parameters(self):
        result = direct("pytest_subtests_failed")
        self.assertIn("✗ sub/test_sub.py::T::test_some_subtests_fail (n=2)\n", result)
        self.assertIn("✗ sub/test_sub.py::T::test_some_subtests_fail (n=3)\n", result)
        self.assertIn("AssertionError: 3 not less than 2", result)

    def test_collection_errors(self):
        result = direct("pytest_collection_error")
        self.assertIn("✗ broken/test_collect.py (collection error)", result)
        self.assertIn("No module named 'module_that_does_not_exist'", result)
        self.assertIn("Interrupted: 1 error during collection", result)

    def test_edge_cases(self):
        result = direct("pytest_edge_cases")
        # The same test name in two files stays two distinct failures.
        self.assertIn("✗ edge/test_dup_a.py::test_same_name", result)
        self.assertIn("✗ edge/test_dup_b.py::test_same_name", result)
        # A test can fail and also error in teardown.
        self.assertIn("(teardown error)", result)
        self.assertIn("teardown exploded", result)
        # Both ends of a chained exception survive.
        self.assertIn("the root cause", result)
        self.assertIn("the surfaced error", result)
        # A huge diff is trimmed, with a note.
        self.assertIn("more lines in the log", result)


class SuccessTest(unittest.TestCase):
    def test_all_passed_is_one_line(self):
        result = direct("pytest_all_passed")
        self.assertRegex(result, r"^✓ 60 passed in [\d.]+s$")

    def test_subtest_totals_are_recognized(self):
        # Exact totals line from a real `pytest -q` run of this project's own tests.
        totals = "27 passed, 59 subtests passed in 0.03s"
        self.assertEqual(pytest.squeeze(totals, 0), f"✓ {totals}")
        self.assertRegex(direct("pytest_subtests_passed"), r"^✓ 1 passed in [\d.]+s$")

    def test_no_tests_is_not_called_a_pass(self):
        self.assertRegex(direct("pytest_no_tests"), r"^60 deselected in [\d.]+s$")


class NeverHideAFailureTest(unittest.TestCase):
    def assert_refuses(self, name, exit_code=None):
        output = squeezers.clean(load(name))
        with self.assertRaises(ValueError):
            pytest.squeeze(output, EXIT_CODES[name] if exit_code is None else exit_code)

    def test_usage_errors_go_to_generic(self):
        self.assert_refuses("pytest_usage_error")
        self.assertIn("unrecognized arguments: --not-a-flag", run("pytest_usage_error"))

    def test_passing_tests_with_a_failing_exit_code_are_not_a_pass(self):
        # A coverage plugin does exactly this: all tests pass, exit 1.
        self.assert_refuses("pytest_all_passed", exit_code=1)
        self.assertNotIn("✓", run("pytest_all_passed", exit_code=1))

    def test_coverage_threshold_failure_is_explained_and_not_a_pass(self):
        result = direct("pytest_cov_threshold_only")
        self.assertRegex(result, r"^60 passed in [\d.]+s\nFAIL Required test coverage of 90% not reached")
        self.assertNotIn("✓", result)

    def test_coverage_failure_shows_alongside_failed_tests(self):
        output = load("pytest_failures").replace(
            "=========================== short test summary info",
            "FAIL Required test coverage of 90% not reached. Total coverage: 12.00%\n"
            "=========================== short test summary info",
        )
        result = pytest.squeeze(squeezers.clean(output), 1)
        self.assertIn("FAIL Required test coverage of 90% not reached", result)
        self.assertIn("✗ tests/test_auth.py::test_refresh_token", result)

    def test_reached_coverage_stays_quiet(self):
        self.assertNotIn("coverage", direct("pytest_cov_with_failures").lower())

    def test_a_fake_section_cannot_lose_a_failure(self):
        # A test printed "=== fake section ===", which ends the FAILURES section early.
        # The block after it is lost, but the summary line still reports that test.
        result = direct("pytest_fake_section")
        self.assertIn("✗ fake/test_fake.py::test_prints_a_fake_section", result)
        self.assertIn("✗ fake/test_fake.py::test_after_the_fake_section", result)

    def test_a_failure_count_mismatch_goes_to_generic(self):
        # With the summary gone too, we find fewer failures than pytest's totals claim.
        lines = squeezers.clean(load("pytest_fake_section")).split("\n")
        output = "\n".join(line for line in lines if not line.startswith("FAILED "))
        with self.assertRaises(ValueError):
            pytest.squeeze(output, 1)
        self.assertIn("test_after_the_fake_section", squeezers.squeeze(["pytest"], output, 1))

    def test_a_truncated_run_goes_to_generic(self):
        output = squeezers.clean(load("pytest_failures")).rsplit("\n", 1)[0]
        with self.assertRaises(ValueError):
            pytest.squeeze(output, 1)
        result = squeezers.squeeze(["pytest"], output, 1)
        self.assertIn("test_refresh_token", result)
        self.assertEqual(generic.squeeze(output, 1), result)

    def test_failures_show_even_if_the_exit_code_says_success(self):
        # A wrapper script can swallow the exit code: `pytest; exit 0`.
        result = squeezers.squeeze(["sh"], load("pytest_failures"), 0)
        self.assertNotIn("✓", result)
        self.assertIn("✗ tests/test_auth.py::test_refresh_token", result)


class MatchesTest(unittest.TestCase):
    def test_commands(self):
        for command in (["pytest"], ["/venv/bin/pytest", "-q"], ["python", "-m", "pytest"], ["uv", "run", "py.test"]):
            with self.subTest(command):
                self.assertTrue(pytest.matches(command, ""))
        self.assertFalse(pytest.matches(["ls"], "some output"))

    def test_wrappers_are_recognized_by_their_output(self):
        self.assertTrue(pytest.matches(["make", "test"], load("pytest_failures")))


if __name__ == "__main__":
    unittest.main()
