"""Regression tests for MangaNana logic that does not require Calibre or Qt."""

import ast
from pathlib import Path
import re
import unittest
import urllib.parse


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MAIN_SOURCE = REPOSITORY_ROOT / "main.py"


def load_main_helpers(*names, globals_=None):
    """Load selected definitions from main.py without importing its GUI runtime."""
    tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"), filename=str(MAIN_SOURCE))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    namespace = dict(globals_ or {})
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MAIN_SOURCE), "exec"), namespace)
    return namespace


class VolumeHelpersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = load_main_helpers(
            "manga_uuid",
            "volume_from_name",
            "fmt_volume",
            "fetch_download_plan",
            globals_={
                "UUID_RE": re.compile(r"/title/([0-9a-fA-F-]{36})"),
                "VOL_RE": re.compile(r"(?i)(?:vol(?:ume)?\.?\s*)(\d+(?:\.\d+)?)"),
            },
        )

    def test_volume_name_normalization(self):
        volume_from_name = self.helpers["volume_from_name"]
        self.assertEqual(volume_from_name("Series Volume 02"), 2.0)
        self.assertEqual(volume_from_name("Series Vol. 12.5"), 12.5)
        self.assertIsNone(volume_from_name("Standalone Chapters"))

    def test_volume_display_normalization(self):
        fmt_volume = self.helpers["fmt_volume"]
        self.assertEqual(fmt_volume(2), "02")
        self.assertEqual(fmt_volume(2, zero_pad=False), "2")
        self.assertEqual(fmt_volume(12.5), "12.5")

    def test_download_plan_sorts_numeric_volumes(self):
        self.helpers["_plan_from_aggregate"] = lambda *_args, **_kwargs: (
            {10.0: 2, 2.5: 1},
            0,
        )
        self.helpers["_plan_from_feed"] = lambda *_args, **_kwargs: (
            {1.0: 3, 10.0: 1},
            0,
        )
        plan = self.helpers["fetch_download_plan"](
            "https://mangadex.org/title/12345678-1234-1234-1234-123456789abc",
            "en",
        )
        self.assertEqual(plan["volumes"], [1.0, 2.5, 10.0])
        self.assertEqual(plan["chapters_by_volume"], {1.0: 3, 2.5: 1, 10.0: 2})


class StandaloneChapterOrderingTests(unittest.TestCase):
    def test_standalone_chapters_follow_requested_numeric_api_order(self):
        requested_urls = []
        rows = [
            {"id": "chapter-1", "attributes": {"chapter": "1", "volume": None}},
            {"id": "duplicate-1", "attributes": {"chapter": "1", "volume": None}},
            {"id": "chapter-2", "attributes": {"chapter": "2", "volume": None}},
            {"id": "chapter-10", "attributes": {"chapter": "10", "volume": None}},
        ]

        def fake_api_json(url, **_kwargs):
            requested_urls.append(url)
            return {"data": rows}

        helpers = load_main_helpers(
            "manga_uuid",
            "fetch_chapter_entries",
            globals_={
                "UUID_RE": re.compile(r"/title/([0-9a-fA-F-]{36})"),
                "urllib": urllib,
                "api_json": fake_api_json,
            },
        )
        entries = helpers["fetch_chapter_entries"](
            "https://mangadex.org/title/12345678-1234-1234-1234-123456789abc",
            "en",
        )

        self.assertEqual([entry["chapter"] for entry in entries], ["1", "2", "10"])
        query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
        self.assertEqual(query["order[volume]"], ["asc"])
        self.assertEqual(query["order[chapter]"], ["asc"])


class LanguageFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = load_main_helpers("first_localized", "choose_preferred_title")

    def test_localized_value_falls_back_to_english(self):
        first_localized = self.helpers["first_localized"]
        self.assertEqual(first_localized({"ja": "日本語", "en": "English"}, "fr"), "English")

    def test_localized_value_falls_back_to_first_available(self):
        first_localized = self.helpers["first_localized"]
        self.assertEqual(first_localized({"ja": "日本語", "de": "Deutsch"}, "fr"), "日本語")

    def test_title_selection_prefers_requested_then_english(self):
        choose_preferred_title = self.helpers["choose_preferred_title"]
        rows = [
            {"language": "ja", "title": "日本語"},
            {"language": "en", "title": "English"},
            {"language": "fr", "title": "Français"},
        ]
        self.assertEqual(choose_preferred_title(rows, "fr"), "Français")
        self.assertEqual(choose_preferred_title(rows, "de"), "English")


if __name__ == "__main__":
    unittest.main()
