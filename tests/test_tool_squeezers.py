"""Fixtures are real tool output, with only absolute temp paths rewritten."""
import re
import unittest
from pathlib import Path

from squeeze import squeezers
from squeeze.squeezers import generic, jest, npm, pip, tsc

FIXTURES = Path(__file__).parent / "fixtures"

# Fixture → (the exit code the tool really returned, the command that ran it).
FIXTURE_RUNS = {
    "npm_install_deprecated": (0, ["npm", "install", "request", "lodash"]),
    "npm_install_up_to_date": (0, ["npm", "install"]),
    "npm_install_force": (0, ["npm", "install", "--force"]),
    "npm_install_404": (1, ["npm", "install", "nope"]),
    "npm_install_eresolve": (1, ["npm", "install", "react@17"]),
    "npm_install_script_fail": (3, ["npm", "install"]),
    "pnpm_install_success": (0, ["pnpm", "add", "request"]),
    "pnpm_install_404": (1, ["pnpm", "add", "nope"]),
    "yarn_install_success": (0, ["yarn", "add", "request"]),
    "yarn_install_404": (1, ["yarn", "add", "nope"]),
    "pip_install_success": (0, ["pip", "install", "requests", "flask"]),
    "pip_install_already": (0, ["pip", "install", "requests", "flask"]),
    "pip_install_local_build": (0, ["pip", "install", "./needsold"]),
    "pip_install_replaces_package": (0, ["pip", "install", "idna==3.7"]),
    "pip_install_not_found": (1, ["pip", "install", "nope"]),
    "pip_install_resolution_conflict": (1, ["pip", "install", "requests==2.31.0"]),
    "pip_install_build_fail": (1, ["pip", "install", "./badpkg"]),
    "tsc_errors": (1, ["tsc"]),
    "tsc_errors_pretty": (1, ["tsc", "--pretty"]),
    "tsc_success": (0, ["tsc"]),
    "tsc_config_error": (2, ["tsc"]),
    "jest_failures": (1, ["jest"]),
    "jest_failures_verbose": (1, ["jest", "--verbose"]),
    "jest_filtered_pass": (0, ["jest", "src/pass.test.js"]),
    "jest_no_tests": (1, ["jest", "nothing"]),
    "jest_coverage_threshold": (1, ["jest", "--coverage"]),
    "jest_only_broken_suite": (1, ["jest", "src/broken.test.js"]),
    "jest_many_suites": (1, ["jest"]),
    "jest_via_npm_test": (1, ["npm", "test"]),
    "vitest_failures": (1, ["vitest", "run"]),
    "vitest_filtered_pass": (0, ["vitest", "run", "src/pass.test.js"]),
    "vitest_no_tests": (1, ["vitest", "run", "nothing"]),
    "vitest_only_broken_suite": (1, ["vitest", "run", "src/broken.test.js"]),
    "vitest_grouped_errors": (1, ["vitest", "run"]),
    "vitest_unhandled_error": (1, ["vitest", "run"]),
    # Older or alternative versions of the same tools.
    "npm_v9_deprecated": (0, ["npm", "install", "request"]),
    "npm_v9_404": (1, ["npm", "install", "nope"]),
    "pnpm_v9_success": (0, ["pnpm", "add", "request"]),
    "pnpm_v9_404": (1, ["pnpm", "add", "nope"]),
    "yarn_berry_success": (0, ["yarn", "add", "request"]),
    "yarn_berry_404": (1, ["yarn", "add", "nope"]),
    "uv_pip_success": (0, ["uv", "pip", "install", "requests"]),
    "uv_pip_already": (0, ["uv", "pip", "install", "requests"]),
    "uv_pip_not_found": (1, ["uv", "pip", "install", "nope"]),
    "tsc_v50_errors": (2, ["tsc"]),
    "tsc_v50_errors_pretty": (2, ["tsc", "--pretty"]),
    "jest_v29_failures": (1, ["jest"]),
    "jest_v29_passed": (0, ["jest", "src/pass.test.js"]),
    "vitest_v3_failures": (1, ["vitest", "run"]),
    "vitest_v3_passed": (0, ["vitest", "run", "src/pass.test.js"]),
}

# These have no parsable result, so they must reach the generic squeezer.
EXPECTED_FALLBACKS = {"jest_no_tests", "vitest_no_tests", "vitest_unhandled_error"}


def load(name):
    return (FIXTURES / f"{name}.txt").read_text()


def run(name):
    exit_code, command = FIXTURE_RUNS[name]
    return squeezers.squeeze(command, load(name), exit_code)


def is_generic_result(name):
    exit_code, _ = FIXTURE_RUNS[name]
    return run(name) == generic.squeeze(squeezers.clean(load(name)), exit_code)


class EveryFixtureTest(unittest.TestCase):
    def test_all_fixtures_are_covered(self):
        known = {path.stem for path in FIXTURES.glob("*.txt") if not path.stem.startswith("pytest_")}
        self.assertEqual(known, set(FIXTURE_RUNS))

    def test_only_a_real_success_gets_a_checkmark(self):
        for name, (exit_code, _) in FIXTURE_RUNS.items():
            with self.subTest(name):
                self.assertEqual("✓" in run(name), exit_code == 0)

    def test_every_fixture_has_output(self):
        for name in FIXTURE_RUNS:
            with self.subTest(name):
                self.assertTrue(run(name).strip())

    def test_output_never_grows(self):
        for name in FIXTURE_RUNS:
            with self.subTest(name):
                if load(name):
                    # Very short output can gain a few characters from a totals line.
                    self.assertLessEqual(len(run(name)), len(load(name)) + 20)

    def test_specific_squeezer_handles_each_fixture(self):
        for name in FIXTURE_RUNS:
            with self.subTest(name):
                if name in EXPECTED_FALLBACKS:
                    self.assertTrue(is_generic_result(name))
                else:
                    self.assertFalse(is_generic_result(name))


class NpmTest(unittest.TestCase):
    def test_success_is_short(self):
        self.assertEqual(
            run("npm_install_deprecated"),
            "✓ added 48 packages, and audited 49 packages in 807ms\n"
            "5 vulnerabilities (3 moderate, 2 critical)\n"
            "⚠ 3 deprecated packages — hidden",
        )

    def test_up_to_date(self):
        self.assertTrue(run("npm_install_up_to_date").startswith("✓ up to date, audited 49 packages"))

    def test_peer_conflicts_are_kept_on_success(self):
        result = run("npm_install_force")
        self.assertIn('npm warn peer react@"^18.3.1" from react-dom@18.3.1', result)
        self.assertIn("✓ added 6 packages", result)

    def test_peer_conflicts_are_kept_on_failure(self):
        result = run("npm_install_eresolve")
        self.assertIn("ERESOLVE unable to resolve dependency tree", result)
        self.assertIn('npm error peer react@"^18.3.1" from react-dom@18.3.1', result)
        self.assertIn("--legacy-peer-deps", result)
        self.assertNotIn("A complete log of this run", result)

    def test_404_keeps_the_package_name(self):
        result = run("npm_install_404")
        self.assertIn("npm error code E404", result)
        self.assertIn("this-package-does-not-exist-sq-98765", result)

    def test_a_failing_script_keeps_its_own_output(self):
        # This line has no "npm error" prefix, and it is the actual cause.
        self.assertIn("boom in postinstall", run("npm_install_script_fail"))

    def test_pnpm(self):
        result = run("pnpm_install_success")
        self.assertTrue(result.startswith("✓ Packages: +48 · Done in 557ms"))
        self.assertIn("⚠ 3 deprecated packages — hidden", result)
        self.assertNotIn("Progress:", result)
        self.assertNotIn("Content-addressable", result)
        self.assertIn("this-package-does-not-exist-sq-", run("pnpm_install_404"))

    def test_yarn(self):
        result = run("yarn_install_success")
        self.assertEqual(result, "✓ success Saved 46 new dependencies. · Done in 1.00s.\n⚠ 3 deprecated packages — hidden")
        failure = run("yarn_install_404")
        self.assertIn("this-package-does-not-exist-sq-98765: Not found", failure)
        self.assertNotIn("cli.js", failure)

    def test_yarn_2_and_later(self):
        self.assertEqual(
            run("yarn_berry_success").split("\n")[0],
            "✓ 49 packages were added to the project (+ 5.55 MiB). · Done with warnings in 0s 784ms",
        )
        self.assertNotIn("YN0085", run("yarn_berry_success"))
        self.assertIn("Package not found", run("yarn_berry_404"))
        self.assertIn("Response Code: 404", run("yarn_berry_404"))

    def test_older_npm_and_pnpm(self):
        self.assertIn("⚠ 3 deprecated packages — hidden", run("npm_v9_deprecated"))
        self.assertNotIn("npm WARN", run("npm_v9_deprecated"))
        self.assertIn("this-package-does-not-exist-sq-98765", run("npm_v9_404"))
        self.assertNotIn("A complete log", run("npm_v9_404"))
        self.assertTrue(run("pnpm_v9_success").startswith("✓ Packages: +48 · Done in 905ms"))
        self.assertNotIn("+ request", run("pnpm_v9_success"))
        self.assertIn("⚠ 3 deprecated packages — hidden", run("pnpm_v9_success"))
        self.assertIn("this-package-does-not-exist-sq-98765", run("pnpm_v9_404"))

    def test_unrecognized_lines_survive(self):
        result = npm.squeeze("added 1 package in 1s\nsomething new we never saw", 0)
        self.assertIn("something new we never saw", result)

    def test_a_scripts_own_output_is_never_mistaken_for_noise(self):
        output = "- step failed: missing header\n+ retrying with 2 workers\n    at build (scripts/build.js:9:3)\n"
        result = npm.squeeze(output, 1)
        self.assertIn("- step failed: missing header", result)
        self.assertIn("+ retrying with 2 workers", result)
        self.assertIn("scripts/build.js:9:3", result)

    def test_yarn_peer_warnings_are_not_counted_as_deprecations(self):
        line = 'warning " > react-dom@18.3.1" has unmet peer dependency "react@^18.3.1".'
        self.assertIn(line, npm.squeeze(f"{line}\nDone in 1.00s.", 0))

    def test_matches_only_installs(self):
        for command in (["npm", "install"], ["npm", "i", "x"], ["npm", "--silent", "ci"], ["pnpm", "add", "x"], ["yarn"]):
            with self.subTest(command):
                self.assertTrue(npm.matches(command, ""))
        for command in (["npm", "test"], ["npm", "run", "build"], ["yarn", "jest"], ["npm"], ["ls", "install"]):
            with self.subTest(command):
                self.assertFalse(npm.matches(command, ""))


class PipTest(unittest.TestCase):
    def test_success_shortens_the_package_list(self):
        self.assertEqual(
            run("pip_install_success"),
            "✓ installed 12 packages: blinker-1.9.0, certifi-2026.10.23, charset_normalizer-3.5.2, +9 more",
        )

    def test_already_satisfied_is_a_count(self):
        self.assertEqual(run("pip_install_already"), "✓ 12 already satisfied")

    def test_short_lists_are_shown_whole(self):
        self.assertEqual(run("pip_install_replaces_package"), "✓ installed 1 package: idna-3.7")

    def test_local_build_noise_is_dropped(self):
        self.assertEqual(run("pip_install_local_build"), "✓ installed 1 package: needsold-1.0")

    def test_not_found(self):
        result = run("pip_install_not_found")
        self.assertIn("Could not find a version that satisfies the requirement", result)
        self.assertIn("No matching distribution found", result)
        self.assertNotIn("[notice]", result)

    def test_resolution_conflicts_keep_their_cause(self):
        result = run("pip_install_resolution_conflict")
        self.assertIn("Cannot install requests==2.31.0 and urllib3==1.20", result)
        self.assertIn("requests 2.31.0 depends on urllib3<3 and >=1.21.1", result)
        self.assertIn("ResolutionImpossible", result)
        self.assertNotIn("Downloading", result)

    def test_build_failures_keep_the_real_error(self):
        result = run("pip_install_build_fail")
        self.assertIn("error: could not find libfoo headers", result)
        self.assertIn("finished with status 'error'", result)
        self.assertNotIn("started", result)

    def test_lines_starting_with_b_are_not_mistaken_for_progress(self):
        # Regression: an old progress-bar pattern matched anything starting with "B".
        for line in ("Build failed: no compiler", "BUG: broken wheel", "MB limit exceeded"):
            with self.subTest(line):
                self.assertIn(line, pip.squeeze(f"{line}\n", 1))

    def test_uv(self):
        self.assertEqual(run("uv_pip_success"), "✓ Installed 12 packages in 9ms")
        self.assertEqual(run("uv_pip_already"), "✓ Checked 2 packages in 3ms")
        result = run("uv_pip_not_found")
        self.assertIn("No solution found when resolving dependencies", result)
        self.assertIn("this-package-does-not-exist-sq-98765", result)

    def test_a_failed_install_never_reports_satisfied_requirements(self):
        output = "Requirement already satisfied: idna\nERROR: Cannot install x\n"
        self.assertEqual(pip.squeeze(output, 1), "ERROR: Cannot install x")

    def test_conflict_warnings_survive(self):
        # pip's check output, which can't be triggered on demand with this pip version.
        warning = "ERROR: flask 3.1 has requirement click>=8, but you'll have click 7.0 which is incompatible."
        result = pip.squeeze(f"Collecting click\n{warning}\nSuccessfully installed click-7.0\n", 0)
        self.assertIn(warning, result)

    def test_matches_only_installs(self):
        for command in (["pip", "install", "x"], ["pip3", "install", "x"], ["python", "-m", "pip", "install", "x"], ["/venv/bin/pip3.14", "install"]):
            with self.subTest(command):
                self.assertTrue(pip.matches(command, ""))
        for command in (["pip", "list"], ["npm", "install"], ["make", "install"]):
            with self.subTest(command):
                self.assertFalse(pip.matches(command, ""))

    def test_installing_pytest_is_not_a_test_run(self):
        result = squeezers.squeeze(["pip", "install", "pytest"], "Collecting pytest\nSuccessfully installed pytest-9.2.0\n", 0)
        self.assertEqual(result, "✓ installed 1 package: pytest-9.2.0")


class TscTest(unittest.TestCase):
    def test_errors_are_file_line_message(self):
        result = run("tsc_errors")
        self.assertTrue(result.startswith("8 errors in 2 files\n"))
        self.assertIn("src/a.ts:3 — TS2339: Property 'nope' does not exist on type 'string'.", result)
        self.assertIn("src/b.ts:4 — TS2307: Cannot find module './does-not-exist'", result)

    def test_details_stay_under_their_error(self):
        self.assertIn(
            "src/b.ts:3 — TS2322: Type '(x: number) => number' is not assignable to type '(x: Deep) => Deep'.\n"
            "  Types of parameters 'x' and 'x' are incompatible.\n",
            run("tsc_errors"),
        )

    def test_pretty_output_matches_plain_output(self):
        self.assertEqual(run("tsc_errors_pretty"), run("tsc_errors"))

    def test_success(self):
        self.assertEqual(run("tsc_success"), "✓ no type errors")

    def test_config_errors_have_no_file(self):
        result = run("tsc_config_error")
        self.assertTrue(result.startswith("2 errors in 1 file\n"))
        self.assertIn("TS18003: No inputs were found", result)
        self.assertIn("tsconfig.json:1 — TS6046", result)

    def test_identical_errors_are_deduplicated(self):
        line = "src/a.ts(1,1): error TS2304: Cannot find name 'x'."
        self.assertEqual(tsc.squeeze(f"{line}\n{line}\n", 1).count("Cannot find name"), 1)

    def test_same_message_on_different_lines_is_kept(self):
        self.assertIn("src/a.ts:2 —", run("tsc_errors"))
        self.assertIn("src/a.ts:1 —", run("tsc_errors"))

    def test_long_types_are_truncated(self):
        result = tsc.squeeze(f"src/a.ts(1,1): error TS2322: Type '{'x' * 5000}' is wrong.\n", 1)
        self.assertLess(len(result), 300)
        self.assertIn("…", result)

    def test_long_detail_chains_are_truncated(self):
        details = "\n".join(f"  level {n}" for n in range(9))
        result = tsc.squeeze(f"src/a.ts(1,1): error TS2322: Bad.\n{details}\n", 1)
        self.assertIn("  level 1\n", result)
        self.assertNotIn("level 2", result)
        self.assertIn("7 more lines in the log", result)

    def test_thousands_of_errors_are_capped_with_a_count_per_file(self):
        output = "\n".join(
            f"src/{'big' if n % 4 else 'small'}.ts({n},1): error TS2304: Cannot find name 'x{n}'." for n in range(1, 1001)
        )
        result = tsc.squeeze(output, 1)
        self.assertTrue(result.startswith("1000 errors in 2 files\n"))
        self.assertLess(len(result.split("\n")), 60)
        self.assertIn("… 950 more errors in the log: src/big.ts ×712, src/small.ts ×238", result)

    def test_older_typescript(self):
        self.assertTrue(run("tsc_v50_errors").startswith("8 errors in 2 files\n"))
        self.assertEqual(run("tsc_v50_errors_pretty"), run("tsc_v50_errors"))

    def test_a_pretty_count_mismatch_goes_to_generic(self):
        output = re.sub(r"^.*TS2339.*$", "", squeezers.clean(load("tsc_errors_pretty")), flags=re.MULTILINE)
        with self.assertRaises(ValueError):
            tsc.squeeze(output, 1)

    def test_failure_without_errors_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            tsc.squeeze("", 1)
        self.assertNotIn("✓", squeezers.squeeze(["tsc"], "tsc crashed badly\n", 1))

    def test_other_successful_output_is_kept(self):
        self.assertIn("Version 5", squeezers.squeeze(["tsc", "--version"], "Version 5.9\n", 0))

    def test_wrappers_are_recognized_by_their_output(self):
        self.assertTrue(tsc.matches(["make", "types"], load("tsc_errors")))
        self.assertFalse(tsc.matches(["ls"], "file.ts"))


class JestTest(unittest.TestCase):
    def test_summary_and_failures(self):
        result = run("jest_failures")
        self.assertTrue(result.startswith("tests: 4 failed, 1 skipped, 30 passed, 35 total · suites: 2 failed, 1 passed, 3 total in 0.318 s"))
        self.assertIn("✗ src/fail.test.js › math › adds numbers", result)
        self.assertIn("✗ src/fail.test.js › top level failure", result)
        self.assertIn("Expected: 3\n    Received: -1", result)

    def test_exact_format_of_one_failure(self):
        self.assertIn(
            "✗ src/fail.test.js › math › throws\n"
            "    src/fail.test.js:5\n"
            '    src/math.js:2  function explode() { throw new TypeError("cannot read widget"); }\n'
            "    TypeError: cannot read widget\n",
            run("jest_failures"),
        )

    def test_diffs_are_kept(self):
        result = run("jest_failures")
        self.assertIn('-   "a": 2,', result)
        self.assertIn('+   "a": 1,', result)

    def test_a_suite_that_cannot_run_is_a_failure(self):
        result = run("jest_failures")
        self.assertIn("✗ src/broken.test.js (suite failed to run)", result)
        self.assertIn("Cannot find module './does-not-exist'", result)
        self.assertIn("✗ src/broken.test.js (suite failed to run)", run("jest_only_broken_suite"))

    def test_noise_is_dropped(self):
        for name in ("jest_failures", "jest_failures_verbose"):
            with self.subTest(name):
                result = run(name)
                self.assertNotIn("noise from a passing test", result)
                self.assertNotIn("case 12", result)
                self.assertNotIn("jest-resolve", result)

    def test_console_output_from_failing_files_is_shown(self):
        for name in ("jest_failures", "jest_failures_verbose", "jest_v29_failures"):
            with self.subTest(name):
                self.assertIn(
                    "console output from failing files:\n  src/fail.test.js\n    debug: inside failing test",
                    run(name),
                )

    def test_older_jest_parses_the_same(self):
        self.assertEqual(run("jest_v29_failures").count("✗"), run("jest_failures").count("✗"))
        self.assertIn("Expected: 3\n    Received: -1", run("jest_v29_failures"))
        self.assertRegex(run("jest_v29_passed"), r"^✓ tests: 30 passed, 30 total in [\d.]+ s$")

    def test_verbose_matches_plain_failures(self):
        self.assertEqual(run("jest_failures_verbose").count("✗"), run("jest_failures").count("✗"))

    def test_pass_is_one_line_despite_console_noise(self):
        self.assertRegex(run("jest_filtered_pass"), r"^✓ tests: 30 passed, 30 total in [\d.]+ s$")

    def test_failures_are_not_repeated_by_the_final_summary(self):
        for name in ("jest_many_suites", "jest_via_npm_test"):
            with self.subTest(name):
                self.assertEqual(run(name).count("✗"), 1)

    def test_coverage_failure_is_explained_and_not_a_pass(self):
        result = run("jest_coverage_threshold")
        self.assertIn('Jest: Coverage for lines (0%) does not meet "global" threshold (100%)', result)
        self.assertNotIn("✓", result)

    def test_no_tests_goes_to_generic(self):
        self.assertIn("No tests found, exiting with code 1", run("jest_no_tests"))

    def test_a_count_mismatch_goes_to_generic(self):
        output = squeezers.clean(load("jest_failures")).replace("  ● math › throws\n", "")
        with self.assertRaises(ValueError):
            jest.squeeze(output, 1)

    def test_passing_totals_with_a_failing_exit_are_not_a_pass(self):
        with self.assertRaises(ValueError):
            jest.squeeze("Test Suites: 1 passed, 1 total\nTests:       1 passed, 1 total\nTime: 1 s\n", 1)

    def test_truncated_output_goes_to_generic(self):
        output = squeezers.clean(load("jest_failures")).split("Test Suites:")[0]
        with self.assertRaises(ValueError):
            jest.squeeze(output, 1)
        self.assertIn("adds numbers", squeezers.squeeze(["jest"], output, 1))


class VitestTest(unittest.TestCase):
    def test_summary_and_failures(self):
        result = run("vitest_failures")
        self.assertTrue(result.startswith("tests: 4 failed, 30 passed, 1 skipped, 35 total · suites: 2 failed, 1 passed, 3 total in 100ms"))
        self.assertIn("✗ src/fail.test.js › math › adds numbers", result)
        self.assertIn("✗ src/fail.test.js › top level failure", result)
        self.assertIn("AssertionError: expected -1 to be 3", result)

    def test_exact_format_of_one_failure(self):
        self.assertIn(
            "✗ src/fail.test.js › math › throws\n"
            "    src/fail.test.js:6\n"
            '    src/math.js:2  export function explode() { throw new TypeError("cannot read widget");…\n'
            "    TypeError: cannot read widget\n",
            run("vitest_failures"),
        )

    def test_a_suite_that_cannot_run_is_a_failure(self):
        for name in ("vitest_failures", "vitest_only_broken_suite"):
            with self.subTest(name):
                result = run(name)
                self.assertIn("✗ src/broken.test.js (suite failed to run)", result)
                self.assertIn("Cannot find module './does-not-exist.js'", result)

    def test_grouped_errors_name_every_test(self):
        result = run("vitest_grouped_errors")
        for name in ("first with shared error", "second with shared error", "each 1", "each 2", "each 3"):
            self.assertIn(f"✗ src/group.test.js › {name}", result)
        self.assertEqual(result.count("Error: identical message"), 1)

    def test_noise_is_dropped(self):
        result = run("vitest_failures")
        self.assertNotIn("noise from a passing test", result)
        self.assertNotIn("RUN", result)
        self.assertNotIn("⎯", result)

    def test_console_output_from_failing_files_is_shown(self):
        for name in ("vitest_failures", "vitest_v3_failures"):
            with self.subTest(name):
                self.assertIn(
                    "console output from failing files:\n  src/fail.test.js\n    debug: inside failing test",
                    run(name),
                )

    def test_older_vitest_parses_the_same(self):
        self.assertEqual(run("vitest_v3_failures").count("✗"), run("vitest_failures").count("✗"))
        self.assertIn("AssertionError: expected -1 to be 3", run("vitest_v3_failures"))
        self.assertRegex(run("vitest_v3_passed"), r"^✓ tests: 30 passed, 30 total in \S+$")

    def test_pass_is_one_line(self):
        self.assertEqual(run("vitest_filtered_pass"), "✓ tests: 30 passed, 30 total in 63ms")

    def test_unhandled_errors_go_to_generic(self):
        # Every test passed and it still exited 1. The reason must stay visible.
        result = run("vitest_unhandled_error")
        self.assertIn("leaked rejection", result)
        self.assertNotIn("✓", result)

    def test_no_tests_goes_to_generic(self):
        self.assertIn("No test files found", run("vitest_no_tests"))

    def test_a_count_mismatch_goes_to_generic(self):
        output = squeezers.clean(load("vitest_failures")).replace(" FAIL  src/fail.test.js > math > throws\n", "")
        with self.assertRaises(ValueError):
            jest.squeeze(output, 1)

    def test_passing_totals_with_a_failing_exit_are_not_a_pass(self):
        with self.assertRaises(ValueError):
            jest.squeeze(" Test Files  1 passed (1)\n      Tests  1 passed (1)\n", 1)


class RoutingTest(unittest.TestCase):
    def test_installing_a_tool_is_an_install(self):
        for package in ("jest", "vitest", "tsc", "pytest"):
            with self.subTest(package):
                result = squeezers.squeeze(["npm", "install", package], "added 1 package in 1s\n", 0)
                self.assertEqual(result, "✓ added 1 package in 1s")

    def test_jest_through_npm_is_recognized_by_its_output(self):
        self.assertTrue(run("jest_via_npm_test").startswith("tests: 1 failed, 24 passed, 25 total"))


if __name__ == "__main__":
    unittest.main()
