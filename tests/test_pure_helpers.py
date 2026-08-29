"""Regression tests for MangaNana logic that does not require Calibre or Qt."""

import ast
from pathlib import Path
import unittest
import urllib.parse

from core_helpers import (
    _iter_aggregate_nodes,
    choose_preferred_title,
    collect_titles,
    first_localized,
    fmt_volume,
    is_doujinshi_entry,
    volume_from_name,
)
from mangadex_source import MangaDexSource


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
            "fetch_download_plan",
            globals_={
                "MANGADEX_SOURCE": MangaDexSource(lambda _url, **_kwargs: None),
            },
        )

    def test_volume_name_normalization(self):
        self.assertEqual(volume_from_name("Series Volume 02"), 2.0)
        self.assertEqual(volume_from_name("Series Vol. 12.5"), 12.5)
        self.assertIsNone(volume_from_name("Standalone Chapters"))

    def test_volume_display_normalization(self):
        self.assertEqual(fmt_volume(2), "02")
        self.assertEqual(fmt_volume(2, zero_pad=False), "2")
        self.assertEqual(fmt_volume(12.5), "12.5")

    def test_download_plan_sorts_numeric_volumes(self):
        def fake_api(url, **_kwargs):
            if "/aggregate?" in url:
                return {"volumes": {
                    "10": {"volume": "10", "count": 2},
                    "2.5": {"volume": "2.5", "count": 1},
                }}
            return {"data": [
                {"id": "one", "attributes": {"volume": "1", "chapter": "1"}},
                {"id": "two", "attributes": {"volume": "1", "chapter": "2"}},
                {"id": "three", "attributes": {"volume": "1", "chapter": "3"}},
                {"id": "ten", "attributes": {"volume": "10", "chapter": "1"}},
            ]}

        plan = MangaDexSource(fake_api).get_download_plan(
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
                "MANGADEX_SOURCE": MangaDexSource(fake_api_json),
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
    def test_localized_value_falls_back_to_english(self):
        self.assertEqual(first_localized({"ja": "日本語", "en": "English"}, "fr"), "English")

    def test_localized_value_falls_back_to_first_available(self):
        self.assertEqual(first_localized({"ja": "日本語", "de": "Deutsch"}, "fr"), "日本語")

    def test_title_selection_prefers_requested_then_english(self):
        rows = [
            {"language": "ja", "title": "日本語"},
            {"language": "en", "title": "English"},
            {"language": "fr", "title": "Français"},
        ]
        self.assertEqual(choose_preferred_title(rows, "fr"), "Français")
        self.assertEqual(choose_preferred_title(rows, "de"), "English")


class MetadataNormalizationTests(unittest.TestCase):
    def test_collect_titles_preserves_order_and_removes_duplicates(self):
        attrs = {
            "title": {"en": " Main Title ", "ja": "日本語"},
            "altTitles": [
                {"en": "main title"},
                {"fr": " Titre "},
                None,
                {"en": "Alternate"},
            ],
        }
        self.assertEqual(
            collect_titles(attrs),
            [
                {"language": "en", "title": "Main Title", "primary": True},
                {"language": "ja", "title": "日本語", "primary": True},
                {"language": "fr", "title": "Titre", "primary": False},
                {"language": "en", "title": "Alternate", "primary": False},
            ],
        )

    def test_doujinshi_detection_uses_tags_and_titles(self):
        tagged = {
            "tags": [{"attributes": {"name": {"en": "Doujinshi"}}}],
        }
        titled = {"title": {"en": "Example Doujin Collection"}}
        ordinary = {"title": {"en": "Ordinary Series"}}
        self.assertTrue(is_doujinshi_entry(tagged))
        self.assertTrue(is_doujinshi_entry(titled))
        self.assertFalse(is_doujinshi_entry(ordinary))


class AggregateNormalizationTests(unittest.TestCase):
    def test_aggregate_mapping_preserves_keys_and_normalizes_empty_rows(self):
        self.assertEqual(
            list(_iter_aggregate_nodes({"1": {"volume": "1"}, "none": None})),
            [("1", {"volume": "1"}), ("none", {})],
        )

    def test_aggregate_list_uses_volume_or_index_as_key(self):
        self.assertEqual(
            list(_iter_aggregate_nodes([{"volume": "2"}, None, "invalid"])),
            [("2", {"volume": "2"}), (None, {}), (2, {})],
        )


if __name__ == "__main__":
    unittest.main()
