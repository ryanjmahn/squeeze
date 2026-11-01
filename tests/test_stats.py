import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from squeeze import dashboard, records, stats

PROJECT = Path(__file__).resolve().parent.parent
SQ = [sys.executable, "-m", "squeeze.cli"]
TODAY = date(2026, 11, 1)  # a Sunday


def run(day=TODAY, before=1000, after=100, tool="pytest", repo="repo-a", command="pytest", raw=False, lines=(100, 10)):
    if raw:
        after, lines = before, (lines[0], lines[0])
    return {
        "v": 1, "ts": f"{day.isoformat()}T12:00:00+09:00", "date": day, "repo": repo, "command": command, "tool": tool,
        "exit": 0, "seconds": 1.0, "lines_before": lines[0], "lines_after": lines[1],
        "tokens_before": before, "tokens_after": after, "raw": raw,
    }


def days_ago(n):
    return TODAY - timedelta(days=n)


class SavedTest(unittest.TestCase):
    def test_raw_runs_save_nothing(self):
        self.assertEqual(stats.saved(run(raw=True)), 0)

    def test_short_commands_can_cost_tokens(self):
        self.assertEqual(stats.saved(run(before=0, after=30)), -30)

    def test_format_compact(self):
        for n, text in ((950, "950"), (4812, "4.8k"), (182_000, "182k"), (1_240_000, "1.24M"), (-30, "-30")):
            self.assertEqual(stats.format_compact(n), text)


class LoadHistoryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, *lines):
        path = self.home / ".squeeze" / "history.jsonl"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def good(self):
        entry = run()
        del entry["date"]
        return json.dumps(entry)

    def test_no_file_is_no_history(self):
        self.assertEqual(stats.load_history(), [])

    def test_date_comes_from_the_recorded_offset(self):
        # 23:30 in Seoul is still the 1st there, whatever timezone reads it later.
        entry = json.loads(self.good())
        entry["ts"] = "2026-11-01T23:30:00+09:00"
        self.write(json.dumps(entry))
        self.assertEqual(stats.load_history()[0]["date"], date(2026, 11, 1))

    def test_damaged_lines_are_skipped(self):
        self.write(
            self.good(), "{not json", "[1, 2]", "42", '{"v": 1}', '{"v": 1, "ts": "nope", "raw": false, "tokens_before": 1, "tokens_after": 1}',
            self.good()[:40], self.good(),
        )
        self.assertEqual(len(stats.load_history()), 2)

    def test_a_future_format_is_skipped_not_misread(self):
        entry = json.loads(self.good())
        entry["v"] = 2
        self.write(json.dumps(entry), self.good())
        self.assertEqual(len(stats.load_history()), 1)


class StreakTest(unittest.TestCase):
    def test_current_streak_counts_back_from_today(self):
        entries = [run(days_ago(n)) for n in (0, 1, 2, 5)]
        self.assertEqual(records.current_streak(entries, TODAY), 3)

    def test_yesterday_keeps_a_streak_alive(self):
        self.assertEqual(records.current_streak([run(days_ago(1)), run(days_ago(2))], TODAY), 2)

    def test_two_days_ago_breaks_it(self):
        self.assertEqual(records.current_streak([run(days_ago(2))], TODAY), 0)

    def test_several_runs_in_a_day_count_once(self):
        self.assertEqual(records.current_streak([run(), run(), run()], TODAY), 1)

    def test_raw_runs_do_not_keep_a_streak(self):
        self.assertEqual(records.current_streak([run(raw=True)], TODAY), 0)

    def test_longest_streak(self):
        entries = [run(days_ago(n)) for n in (0, 1, 10, 11, 12, 13, 20)]
        self.assertEqual(records.longest_streak(entries), 4)
        self.assertEqual(records.longest_streak([]), 0)


class PersonalRecordsTest(unittest.TestCase):
    def test_biggest_squeeze(self):
        small, big = run(before=500), run(before=9000)
        self.assertIs(records.biggest_squeeze([small, big]), big)

    def test_runs_that_saved_nothing_are_not_a_record(self):
        self.assertIsNone(records.biggest_squeeze([run(before=0, after=30)]))
        self.assertIsNone(records.biggest_squeeze([]))

    def test_best_day_adds_up_a_day(self):
        entries = [run(days_ago(1), before=2000), run(TODAY), run(TODAY), run(TODAY)]
        self.assertEqual(records.best_day(entries), (TODAY, 2700))

    def test_percent_never_rounds_up_to_100(self):
        self.assertEqual(records.squeeze_percent(run(lines=(10_000, 1))), 99.9)
        self.assertEqual(records.squeeze_percent(run(lines=(0, 3))), 0)


class BadgeTest(unittest.TestCase):
    def earned(self, *entries):
        return records.earned_badges(list(entries))

    def test_no_history_no_badges(self):
        self.assertEqual(self.earned(), [])

    def test_first_squeeze(self):
        self.assertEqual(self.earned(run()), ["First Squeeze"])

    def test_raw_is_not_a_squeeze(self):
        self.assertEqual(self.earned(run(raw=True)), [])

    def test_clubs(self):
        self.assertIn("100k Club", self.earned(run(before=100_100)))
        self.assertNotIn("100k Club", self.earned(run(before=100_000)))
        self.assertIn("1M Club", self.earned(run(before=1_000_100)))

    def test_week_streak(self):
        self.assertIn("Week Streak", self.earned(*(run(days_ago(n)) for n in range(7))))
        self.assertNotIn("Week Streak", self.earned(*(run(days_ago(n)) for n in range(6))))

    def test_npm_whisperer(self):
        self.assertIn("npm Whisperer", self.earned(*[run(tool="npm")] * 50))
        self.assertNotIn("npm Whisperer", self.earned(*[run(tool="npm")] * 49))
        self.assertNotIn("npm Whisperer", self.earned(*[run(tool="npm", raw=True)] * 50))

    def test_test_marathon_needs_one_week(self):
        self.assertIn("Test Marathon", self.earned(*[run()] * 100))
        spread = [run(days_ago(n % 3 * 14)) for n in range(100)]
        self.assertNotIn("Test Marathon", self.earned(*spread))


class CelebrationTest(unittest.TestCase):
    def test_first_run_is_a_badge_and_not_every_record_at_once(self):
        self.assertEqual(records.celebration([], run()), "🎖 Badge unlocked: First Squeeze")

    def test_nothing_new_is_silent(self):
        self.assertIsNone(records.celebration([run(before=5000)], run(before=2000)))

    def test_new_biggest_squeeze(self):
        line = records.celebration([run(before=2000)], run(before=9000, lines=(4812, 9)))
        self.assertEqual(line, "🏆 New PR: biggest squeeze ever (-99.8%)")

    def test_tiny_records_stay_quiet(self):
        self.assertIsNone(records.celebration([run(before=150)], run(before=400)))

    def test_day_record_fires_once_when_crossed(self):
        history = [run(days_ago(1), before=2100), run(TODAY, before=2000)]  # yesterday 2000 saved, today 1900
        line = records.celebration(history, run(TODAY, before=300, after=100))
        self.assertEqual(line, "🏆 New PR: most tokens saved in a day (2.1k)")
        history.append(run(TODAY, before=300, after=100))
        self.assertIsNone(records.celebration(history, run(TODAY, before=300, after=100)))

    def test_a_first_day_has_nothing_to_beat(self):
        self.assertNotIn("in a day", records.celebration([run(before=500)], run(before=5000)))

    def test_streak_record_fires_once_a_day(self):
        history = [run(days_ago(1))]
        small = run(TODAY, before=100, after=100)
        self.assertEqual(records.celebration(history, small), "🏆 New PR: longest streak (2 days)")
        self.assertIsNone(records.celebration([*history, small], small))

    def test_several_pieces_of_news_stay_on_one_line(self):
        line = records.celebration([run(days_ago(1), before=2000)], run(TODAY, before=200_000))
        self.assertIn("100k Club", line)
        self.assertIn("biggest squeeze", line)
        self.assertNotIn("\n", line)


class EquivalentsTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(dashboard.equivalents(100), "")
        self.assertEqual(dashboard.equivalents(5000), "≈ 10 pages of log spam you didn't read")
        self.assertEqual(
            dashboard.equivalents(600_000),
            "≈ 3.0 context windows · ≈ 5.0 novels' worth of log spam you didn't read",
        )


class DashboardTest(unittest.TestCase):
    def week(self):
        return [
            run(days_ago(6), before=182_100, tool="pytest"),  # Monday
            run(days_ago(5), before=301_100, tool="npm", repo="repo-b", command="npm", lines=(4812, 9)),
            run(days_ago(4), before=94_100, tool="tsc"),
            run(days_ago(9), before=100_100, tool="pytest"),  # last week
        ]

    def test_week_shows_the_spec_layout(self):
        text = dashboard.render(self.week(), "week", TODAY)
        self.assertRegex(text, r"^🍋 SQUEEZE · this week +Oct 26 – Nov 1\n")
        self.assertIn("577k tokens saved", text)
        self.assertIn("▲ 477% vs last week", text)
        self.assertIn("3 commands squeezed", text)
        self.assertIn("≈ 2.9 context windows", text)
        self.assertIn("Mon ▇▇▇▇▇▇▇       182k", text)
        self.assertIn("Tue ▇▇▇▇▇▇▇▇▇▇▇▇  301k", text)
        self.assertIn("Sun               —", text)
        self.assertIn("Top tools        npm 52% · pytest 31% · tsc 16%", text)
        self.assertIn("Biggest squeeze  npm · 4,812 → 9 lines (-99.8%) 🏆", text)
        self.assertIn("Top repo         repo-b", text)

    def test_last_week_is_not_counted_in_this_week(self):
        self.assertNotIn("677k", dashboard.render(self.week(), "week", TODAY))

    def test_a_week_with_no_comparison_shows_no_arrow(self):
        text = dashboard.render([run(TODAY)], "week", TODAY)
        self.assertNotIn("vs last week", text)
        self.assertNotIn("▲", text)

    def test_a_drop_points_down(self):
        text = dashboard.render([run(days_ago(9), before=2000, after=0), run(TODAY, before=1000, after=0)], "week", TODAY)
        self.assertIn("▼ 50% vs last week", text)

    def test_streak(self):
        text = dashboard.render([run(days_ago(n)) for n in range(6)], "week", TODAY)
        self.assertIn("🔥 6-day streak", text)
        self.assertNotIn("streak", dashboard.render([run(days_ago(30))], "week", TODAY).split("🏆")[0])

    def test_month_has_week_bars_and_compares_to_last_month(self):
        entries = [run(date(2026, 11, 1), before=1000, after=0), run(date(2026, 10, 1), before=2000, after=0)]
        text = dashboard.render(entries, "month", TODAY)
        self.assertRegex(text, r"this month +November 2026")
        self.assertIn("▼ 50% vs last month", text)
        for label in ("Nov 1 ", "Nov 8 ", "Nov 15", "Nov 22", "Nov 29"):
            self.assertIn(f"   {label}", text)

    def test_comparisons_use_the_same_point_in_the_last_period(self):
        # On the 1st, the rest of October hasn't happened yet as far as a fair comparison goes.
        entries = [run(date(2026, 11, 1), before=1000, after=0), run(date(2026, 10, 1), before=1000, after=0), run(date(2026, 10, 20), before=90_000, after=0)]
        self.assertIn("= 0% vs last month", dashboard.render(entries, "month", TODAY))
        # A Wednesday compares Monday to Wednesday, not last week's whole seven days.
        wednesday = date(2026, 11, 4)
        entries = [run(date(2026, 11, 2), before=1000, after=0), run(date(2026, 10, 27), before=500, after=0), run(date(2026, 10, 31), before=90_000, after=0)]
        self.assertIn("▲ 100% vs last week", dashboard.render(entries, "week", wednesday))

    def test_a_longer_month_compares_with_a_shorter_one(self):
        march = date(2027, 3, 31)
        entries = [run(march, before=1000, after=0), run(date(2027, 2, 28), before=1000, after=0)]
        self.assertIn("= 0% vs last month", dashboard.render(entries, "month", march))

    def test_all_time_has_month_bars_and_no_comparison(self):
        entries = [run(date(2026, 3, 2), before=5000, after=0), run(date(2026, 11, 1), before=1000, after=0)]
        text = dashboard.render(entries, "all", TODAY)
        self.assertRegex(text, r"all time +since Mar 2026")
        self.assertIn("Mar 26", text)
        self.assertIn("Nov 26", text)
        self.assertNotIn(" vs ", text)
        self.assertIn("6.0k tokens saved", text)

    def test_all_time_bars_stop_at_a_year(self):
        entries = [run(date(2024, 1, 15))]
        text = dashboard.render(entries, "all", TODAY)
        self.assertNotIn("Jan 24", text.split("🏆")[0].split("\n\n")[2])
        self.assertIn("Nov 26", text)

    def test_january_compares_with_december(self):
        january = date(2027, 1, 10)
        text = dashboard.render([run(january, before=1000, after=0), run(date(2026, 12, 5), before=1000, after=0)], "month", january)
        self.assertIn("= 0% vs last month", text)

    def test_records_and_badges_are_shown(self):
        text = dashboard.render(self.week(), "week", TODAY)
        self.assertIn("Best day         Oct 27 · 301k tokens", text)
        self.assertIn("Longest streak   3 days", text)
        self.assertIn("🎖 Badges (2/6)  First Squeeze · 100k Club", text)

    def test_an_empty_period_still_renders(self):
        text = dashboard.render([run(days_ago(60))], "week", TODAY)
        self.assertIn("0 tokens saved", text)
        self.assertIn("0 commands squeezed", text)
        self.assertIn("Biggest squeeze  pytest", text)

    def test_only_losses_draw_no_bars(self):
        text = dashboard.render([run(TODAY, before=0, after=30)], "week", TODAY)
        self.assertIn("-30 tokens saved", text)
        self.assertNotIn("▇", text)
        self.assertNotIn("Top tools", text)

    def test_repo_view_names_the_repo_and_skips_top_repo(self):
        text = dashboard.render([run()], "week", TODAY, repo="repo-a")
        self.assertIn("this week · repo-a", text)
        self.assertNotIn("Top repo", text)


class StatsCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve() / "my-repo"
        self.dir.mkdir()
        self.home = Path(tmp.name).resolve() / "home"
        self.home.mkdir()
        self.env = {**os.environ, "PYTHONPATH": str(PROJECT), "HOME": str(self.home)}

    def sq(self, *argv, cwd=None, **kwargs):
        options = {"cwd": cwd or self.dir, "env": self.env, "capture_output": True, "stdin": subprocess.DEVNULL, "timeout": 30}
        return subprocess.run([*SQ, *argv], **{**options, **kwargs})

    def history_path(self):
        return self.home / ".squeeze" / "history.jsonl"

    def test_no_history_says_how_to_start(self):
        result = self.sq("stats")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No squeezes yet. Try: sq pytest", result.stdout.decode())

    def test_real_runs_show_up(self):
        self.sq("sh", "-c", "seq 5000")
        text = self.sq("stats").stdout.decode()
        self.assertIn("🍋 SQUEEZE · this week", text)
        self.assertIn("1 command squeezed", text)
        self.assertIn("Top repo         my-repo", text)

    def test_period_flags(self):
        self.sq("true")
        self.assertIn("this month", self.sq("stats", "--month").stdout.decode())
        self.assertIn("all time", self.sq("stats", "--all").stdout.decode())
        self.assertEqual(self.sq("stats", "--week", "--all").returncode, 2)

    def test_repo_flag_filters(self):
        other = self.dir.parent / "other-repo"
        other.mkdir()
        self.sq("true", cwd=other)
        self.assertIn("No squeezes yet in my-repo", self.sq("stats", "--repo").stdout.decode())
        self.assertIn("this week · other-repo", self.sq("stats", "--repo", cwd=other).stdout.decode())

    def test_stats_leaves_no_trace(self):
        self.sq("stats")
        self.assertFalse(self.history_path().exists())
        self.assertFalse((self.dir / ".squeeze").exists())

    def test_a_real_command_named_stats_is_reachable(self):
        self.assertEqual(self.sq("--", "stats").returncode, 127)

    def test_reset_deletes_only_after_yes(self):
        self.sq("true")
        for answer in (b"", b"n\n", b"nope\n"):
            with self.subTest(answer):
                result = self.sq("stats", "--reset", input=answer, stdin=None)
                self.assertEqual(result.returncode, 0)
                self.assertIn(b"Nothing deleted", result.stdout)
                self.assertTrue(self.history_path().exists())
        result = self.sq("stats", "--reset", input=b"y\n", stdin=None)
        self.assertIn(b"History deleted", result.stdout)
        self.assertFalse(self.history_path().exists())

    def test_reset_without_any_input_deletes_nothing(self):
        self.sq("true")
        self.sq("stats", "--reset")
        self.assertTrue(self.history_path().exists())

    def test_reset_with_no_history(self):
        self.assertIn(b"no history to reset", self.sq("stats", "--reset").stdout)

    def test_reset_leaves_logs_alone(self):
        self.sq("true")
        self.sq("stats", "--reset", input=b"y\n", stdin=None)
        self.assertEqual(len(list(self.dir.glob(".squeeze/logs/*.log"))), 1)

    def test_reset_cannot_look_like_a_partial_reset(self):
        self.sq("true")
        result = self.sq("stats", "--reset", "--repo", input=b"y\n", stdin=None)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.history_path().exists())


class CelebrationInARunTest(StatsCommandTest):
    def test_first_run_celebrates_after_the_log_line(self):
        lines = self.sq("sh", "-c", "seq 500; exit 3").stdout.decode().splitlines()
        self.assertTrue(lines[-2].startswith("full log: "))
        self.assertEqual(lines[-1], "🎖 Badge unlocked: First Squeeze")

    def test_the_exit_code_is_unaffected(self):
        self.assertEqual(self.sq("sh", "-c", "exit 3").returncode, 3)

    def test_the_second_run_is_quiet(self):
        self.sq("true")
        self.assertNotIn("🎖", self.sq("true").stdout.decode())

    def test_the_line_counts_toward_what_was_printed(self):
        result = self.sq("sh", "-c", "seq 500")
        entry = json.loads(self.history_path().read_text().splitlines()[0])
        self.assertEqual(entry["lines_after"], len(result.stdout.splitlines()))
        self.assertEqual(entry["tokens_after"], len(result.stdout.decode()) // 4)

    def test_the_header_count_includes_the_line(self):
        text = self.sq("sh", "-c", "seq 500").stdout.decode()
        self.assertIn("Badge unlocked", text)
        self.assertIn(f"500 lines → {len(text.splitlines())} lines", text.splitlines()[0])

    def test_raw_runs_do_not_celebrate(self):
        result = self.sq("--raw", "true")
        self.assertNotIn("Badge", (result.stdout + result.stderr).decode())

    def test_a_damaged_history_cannot_hurt_a_run(self):
        self.history_path().parent.mkdir()
        self.history_path().write_bytes(b"\xff\xfe garbage\n{broken\n")
        result = self.sq("sh", "-c", "echo fine; exit 4")
        self.assertEqual(result.returncode, 4)
        self.assertIn(b"fine", result.stdout)

    def test_an_unreadable_history_cannot_hurt_a_run(self):
        (self.home / ".squeeze").write_text("a file where the directory should be")
        result = self.sq("sh", "-c", "echo fine; exit 4")
        self.assertEqual(result.returncode, 4)
        self.assertIn(b"fine", result.stdout)


if __name__ == "__main__":
    unittest.main()
