"""The README makes promises a reader will copy and paste, so hold it to them."""
import importlib.util
import re
import unittest
from pathlib import Path
from unittest import mock

from squeeze import cli, squeezers

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
SQUEEZERS_DOC = (ROOT / "docs" / "squeezers.md").read_text()


class ReadmeTest(unittest.TestCase):
    def example_squeezer(self):
        code = re.search(r"```python\n(# squeeze/squeezers/cargo\.py.*?)```", SQUEEZERS_DOC, re.DOTALL)[1]
        namespace = {"__name__": "squeeze.squeezers.cargo"}
        exec(code, namespace)
        return mock.Mock(__name__="squeeze.squeezers.cargo", matches=namespace["matches"], squeeze=namespace["squeeze"])

    def test_the_snippet_matches_sq_init(self):
        self.assertIn(cli.CLAUDE_SNIPPET, README)

    def test_the_example_squeezer_works(self):
        example = self.example_squeezer()
        with mock.patch.object(squeezers, "SQUEEZERS", [example]):
            passing = "running 2 tests\ntest result: ok. 2 passed; 0 failed\n"
            self.assertEqual(squeezers.squeeze(["cargo", "test"], passing, 0), ("✓ test result: ok. 2 passed; 0 failed", "cargo"))
            failing = "test math::adds ... FAILED\ntest result: FAILED. 1 passed; 1 failed\n"
            text, tool = squeezers.squeeze(["cargo", "test"], failing, 101)
            self.assertEqual(text, "test result: FAILED. 1 passed; 1 failed\n✗ math::adds")
            self.assertEqual(tool, "cargo")

    def test_the_example_squeezer_falls_back_as_described(self):
        example = self.example_squeezer()
        with mock.patch.object(squeezers, "SQUEEZERS", [example]):
            text, tool = squeezers.squeeze(["cargo", "test"], "error: could not compile\n", 101)
        self.assertEqual(tool, "generic")
        self.assertIn("could not compile", text)
        self.assertFalse(example.matches(["cargo", "build"], ""))

    def test_every_squeezer_is_documented(self):
        for tool in ("pytest", "jest", "vitest", "npm", "pnpm", "yarn", "pip", "uv pip", "tsc"):
            self.assertIn(tool, README)
            self.assertIn(tool, SQUEEZERS_DOC)

    def test_relative_links_point_at_real_files_and_headings(self):
        for path in (ROOT / "README.md", *(ROOT / "docs").glob("*.md")):
            for target in re.findall(r"\]\((?!https?:)([^)#]*)(?:#([^)]*))?\)", path.read_text()):
                file, anchor = target
                linked = (path.parent / file).resolve() if file else path
                with self.subTest(source=path.name, target=target):
                    self.assertTrue(linked.exists())
                    if anchor:
                        headings = re.findall(r"(?m)^#+ (.+)$", linked.read_text())
                        slugs = [re.sub(r"[^\w -]", "", h).strip().lower().replace(" ", "-") for h in headings]
                        self.assertIn(anchor, slugs)


class SiteTest(unittest.TestCase):
    PAGE = (ROOT / "docs" / "index.html").read_text()

    def test_local_files_it_references_exist(self):
        for target in re.findall(r'(?:src|href)="(?!https?:|#|data:)([^"]+)"', self.PAGE):
            self.assertTrue((ROOT / "docs" / target).exists(), target)

    def test_in_page_links_have_targets(self):
        for target in re.findall(r'href="#([^"]+)"', self.PAGE):
            self.assertIn(f'id="{target}"', self.PAGE)

    def test_the_demo_data_matches_what_the_squeezers_really_do(self):
        # If this fails, a squeezer changed: run `PYTHONPATH=. python3 scripts/build_demo.py`.
        spec = importlib.util.spec_from_file_location("build_demo", ROOT / "scripts" / "build_demo.py")
        build_demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_demo)
        self.assertEqual((ROOT / "docs" / "demo-data.js").read_text(), build_demo.build())

    def test_the_demo_has_no_personal_paths(self):
        data = (ROOT / "docs" / "demo-data.js").read_text()
        self.assertNotIn("/Users/", data)
        self.assertNotIn("/private/", data)

    def test_the_example_card_is_labelled_until_it_is_real(self):
        self.assertIn("made-up numbers", self.PAGE)
        self.assertTrue((ROOT / "docs" / "card.svg").exists())

    def test_it_makes_no_open_source_claim_without_a_license(self):
        if not list(ROOT.glob("LICENSE*")):
            self.assertNotIn("open source", self.PAGE.lower())

    def test_personal_paths_never_ship(self):
        self.assertNotIn("/Users/", self.PAGE)
        self.assertNotIn("/private/", self.PAGE)


if __name__ == "__main__":
    unittest.main()
