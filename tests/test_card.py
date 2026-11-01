import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

from squeeze import card, dashboard

PROJECT = Path(__file__).resolve().parent.parent
SQ = [sys.executable, "-m", "squeeze.cli"]
SVG = "{http://www.w3.org/2000/svg}"
TODAY = date(2026, 11, 1)  # a Sunday


def run(day=TODAY, before=1000, after=100, tool="pytest", command="pytest", repo="secret-client-project", lines=(100, 10)):
    return {
        "v": 1, "ts": f"{day}T12:00:00+09:00", "date": day, "repo": repo, "command": command, "tool": tool, "exit": 0,
        "seconds": 1.0, "lines_before": lines[0], "lines_after": lines[1], "tokens_before": before, "tokens_after": after, "raw": False,
    }


def week():
    return [
        run(TODAY - timedelta(days=6), before=182_100),
        run(TODAY - timedelta(days=5), before=301_100, tool="npm", command="npm", lines=(4812, 9)),
        run(TODAY, before=94_100, tool="tsc", command="tsc"),
        run(TODAY - timedelta(days=9), before=100_100),
    ]


def texts(svg):
    return ["".join(node.itertext()) for node in ET.fromstring(svg).iter(f"{SVG}text")]


class SvgTest(unittest.TestCase):
    def setUp(self):
        self.svg = card.render_svg(week(), "week", TODAY)

    def test_is_well_formed_with_a_fixed_size(self):
        root = ET.fromstring(self.svg)
        self.assertEqual(root.get("viewBox"), "0 0 1200 630")

    def test_shows_what_the_spec_lists(self):
        shown = texts(self.svg)
        self.assertIn("577k", shown)
        self.assertIn("tokens saved (est.)", shown)
        self.assertIn("🍋 SQUEEZE", shown)
        self.assertIn("THIS WEEK · OCT 26 – NOV 1", shown)
        self.assertIn("≈ 2.9 context windows", shown)
        self.assertIn("day streak", shown)
        self.assertIn("+477%", shown)
        self.assertIn("vs last week", shown)
        self.assertIn("npm · 4,812 → 9 lines (-99.8%)", shown)
        self.assertIn("Oct 27 · 301k tokens", shown)
        self.assertIn("pytest", shown)
        self.assertIn("First Squeeze", shown)

    def test_a_repo_name_never_reaches_a_shareable_card(self):
        self.assertNotIn("secret-client-project", self.svg)

    def test_has_no_external_references_or_scripts(self):
        without_namespace = self.svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
        for banned in ("http:", "https:", "href", "<script", "<image", "@import", "url("):
            self.assertNotIn(banned, without_namespace)

    def test_describes_itself_for_screen_readers(self):
        root = ET.fromstring(self.svg)
        self.assertEqual(root.get("role"), "img")
        self.assertIn("577k tokens saved", root.find(f"{SVG}title").text)
        description = root.find(f"{SVG}desc").text
        self.assertIn("Mon: 182k.", description)
        self.assertIn("Sun: 94k.", description)

    def test_every_bar_is_labelled_and_hoverable(self):
        titles = [node.text for node in ET.fromstring(self.svg).iter(f"{SVG}title")]
        self.assertIn("Tue: 301k tokens saved", titles)
        self.assertIn("Thu: 0 tokens saved", titles)

    def bar_heights(self, svg):
        heights = []
        for path in ET.fromstring(svg).iter(f"{SVG}path"):
            top = path.get("d").split("V")[1].split("Q")[0]
            heights.append(card.CHART_BASE - float(top))
        return heights

    def test_bar_heights_are_proportional(self):
        heights = self.bar_heights(self.svg)
        self.assertEqual(len(heights), 3)
        self.assertAlmostEqual(heights[0] / heights[1], 182 / 301, delta=0.03)

    def test_only_the_peak_gets_a_number(self):
        shown = texts(self.svg)
        self.assertIn("301k", shown)
        self.assertNotIn("182k", shown)

    def test_a_tiny_bar_is_still_visible(self):
        svg = card.render_svg([run(before=1_000_000, after=0), run(TODAY - timedelta(days=1), before=10, after=0)], "week", TODAY)
        self.assertEqual(len(self.bar_heights(svg)), 2)

    def test_hostile_history_values_are_escaped(self):
        svg = card.render_svg([run(command="<script>alert(1)</script>", tool='"><img src=x>')], "week", TODAY)
        ET.fromstring(svg)
        self.assertNotIn("<script", svg)
        self.assertNotIn("<img", svg)


class EdgeCaseTest(unittest.TestCase):
    def test_month_and_all_time(self):
        entries = [run(date(2025, 1, 5)), *week()]
        self.assertIn("THIS MONTH · NOVEMBER 2026", texts(card.render_svg(entries, "month", TODAY)))
        shown = texts(card.render_svg(entries, "all", TODAY))
        self.assertIn("ALL TIME · SINCE JAN 2025", shown)
        self.assertNotIn("vs last week", shown)
        self.assertIn("Nov", shown)
        self.assertNotIn("Nov 26", shown)

    def test_an_empty_period_still_draws(self):
        svg = card.render_svg([run(TODAY - timedelta(days=60))], "week", TODAY)
        self.assertIn("0", texts(svg))
        self.assertEqual(list(ET.fromstring(svg).iter(f"{SVG}path")), [])

    def test_only_losses_draw_no_bars(self):
        svg = card.render_svg([run(before=0, after=30)], "week", TODAY)
        self.assertIn("-30", texts(svg))
        self.assertEqual(list(ET.fromstring(svg).iter(f"{SVG}path")), [])

    def test_huge_totals_stay_short(self):
        shown = texts(card.render_svg([run(before=9_540_000_000, after=0)], "week", TODAY))
        self.assertIn("9.54B", shown)

    def test_long_commands_are_shortened(self):
        svg = card.render_svg([run(command="a-very-long-command-name-that-goes-on", lines=(1_234_567, 12))], "week", TODAY)
        self.assertIn("a-very-long-comm · 1.23M → 12 lines (-99.9%)", texts(svg))

    def test_tools_rounding_to_nothing_get_no_row(self):
        entries = [run(before=1_000_000, after=0), run(before=100, after=0, tool="tsc")]
        self.assertEqual(dashboard.summarize(entries, "week", TODAY).tools, [("pytest", 99)])

    def test_every_badge_fits_inside_the_margins(self):
        svg = card.render_svg([], "week", TODAY)
        x = card.MARGIN
        for name in ("First Squeeze", "100k Club", "1M Club", "Week Streak", "npm Whisperer", "Test Marathon"):
            x += len(name) * 9.2 + 28 + 8
        self.assertLess(x, card.WIDTH - card.MARGIN)
        ET.fromstring(svg)


class HtmlTest(unittest.TestCase):
    def setUp(self):
        self.svg = card.render_svg(week(), "week", TODAY)
        self.html = card.render_html(self.svg)

    def test_wraps_the_same_svg(self):
        self.assertIn(self.svg, self.html)

    def test_is_self_contained(self):
        without_namespace = self.html.replace('xmlns="http://www.w3.org/2000/svg"', "")
        for banned in ("http:", "https:", "<link", "<script", "@import", "src="):
            self.assertNotIn(banned, without_namespace)

    def test_scales_to_small_screens(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn("width: 100%", self.html)
        self.assertIn('charset="utf-8"', self.html)


class CardCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve() / "my-repo"
        self.dir.mkdir()
        home = Path(tmp.name).resolve() / "home"
        home.mkdir()
        self.env = {**os.environ, "PYTHONPATH": str(PROJECT), "HOME": str(home)}

    def sq(self, *argv):
        return subprocess.run([*SQ, *argv], cwd=self.dir, env=self.env, capture_output=True, stdin=subprocess.DEVNULL, timeout=30)

    def cards(self):
        return sorted(path.name for path in self.dir.glob(".squeeze/cards/*"))

    def test_no_history_makes_no_files(self):
        result = self.sq("card")
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"No squeezes yet", result.stdout)
        self.assertEqual(self.cards(), [])
        self.assertFalse((self.dir / ".squeeze").exists())

    def test_saves_both_files_and_prints_their_paths(self):
        self.sq("sh", "-c", "seq 3000")
        result = self.sq("card")
        self.assertEqual(result.returncode, 0)
        for line in result.stdout.decode().splitlines():
            self.assertTrue((self.dir / line.split(maxsplit=1)[1]).is_file())
        stems = self.cards()
        self.assertEqual(len(stems), 2)
        self.assertTrue(stems[0].endswith("_week.html"))
        self.assertTrue(stems[1].endswith("_week.svg"))
        ET.parse(next(self.dir.glob(".squeeze/cards/*.svg")))

    def test_period_flags_choose_the_file(self):
        self.sq("true")
        self.sq("card", "--month")
        self.sq("card", "--all")
        names = " ".join(self.cards())
        self.assertIn("_month.svg", names)
        self.assertIn("_all.svg", names)
        self.assertEqual(self.sq("card", "--week", "--all").returncode, 2)

    def test_a_card_is_not_counted_as_a_run(self):
        self.sq("true")
        before = (Path(self.env["HOME"]) / ".squeeze" / "history.jsonl").read_text()
        self.sq("card")
        self.assertEqual((Path(self.env["HOME"]) / ".squeeze" / "history.jsonl").read_text(), before)

    def test_cards_stay_out_of_git(self):
        (self.dir / ".git").mkdir()
        self.sq("true")
        (self.dir / ".gitignore").unlink()
        self.sq("card")
        self.assertIn(".squeeze/", (self.dir / ".gitignore").read_text())

    def test_a_save_failure_says_so(self):
        self.sq("true")
        cards = self.dir / ".squeeze" / "cards"
        cards.write_text("a file where the directory should be")
        result = self.sq("card")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"could not save the card", result.stderr)

    def test_a_real_command_named_card_is_reachable(self):
        self.assertEqual(self.sq("--", "card").returncode, 127)


if __name__ == "__main__":
    unittest.main()
