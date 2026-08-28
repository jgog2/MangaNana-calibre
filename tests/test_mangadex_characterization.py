"""Offline characterization tests for the current MangaDex integration."""

import ast
import copy
import json
from pathlib import Path
import unittest
import urllib.parse

from core_helpers import (
    _iter_aggregate_nodes,
    choose_preferred_title,
    collect_titles,
)
from mangadex_source import MangaDexSource
from source_adapter import SourceAdapter


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MAIN_SOURCE = REPOSITORY_ROOT / "main.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANGA_ID = "12345678-1234-1234-1234-123456789abc"
MANGA_URL = f"https://mangadex.org/title/{MANGA_ID}"


def load_fixture(name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    page_size = data.pop("testRepeatLastRowToPageSize", None)
    if page_size and data.get("data"):
        data["data"].extend(
            copy.deepcopy(data["data"][-1])
            for _ in range(page_size - len(data["data"]))
        )
    return data


class FixtureAPI:
    """Route MangaDex URLs to saved responses or configured failures."""

    def __init__(
        self,
        *,
        metadata=None,
        aggregate=None,
        feed_pages=None,
        covers=None,
        failures=(),
    ):
        self.metadata = metadata
        self.aggregate = aggregate
        self.feed_pages = feed_pages or {0: {"data": []}}
        self.covers = covers
        self.failures = set(failures)
        self.urls = []

    def __call__(self, url, **_kwargs):
        self.urls.append(url)
        if "/aggregate?" in url:
            operation = "aggregate"
            response = self.aggregate
        elif "/feed?" in url:
            operation = "feed"
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            response = self.feed_pages.get(int(query.get("offset", [0])[0]), {"data": []})
        elif "/cover?" in url:
            operation = "covers"
            response = self.covers
        else:
            operation = "metadata"
            response = self.metadata
        if operation in self.failures:
            raise RuntimeError(f"fixture {operation} failure")
        if response is None:
            raise AssertionError(f"No fixture configured for {operation}: {url}")
        return copy.deepcopy(response)


def load_mangadex_functions(api):
    names = {
        "manga_uuid",
        "load_manga_metadata",
        "_plan_from_aggregate",
        "_plan_from_feed",
        "fetch_download_plan",
        "fetch_chapter_entries",
        "fetch_volume_covers",
    }
    tree = ast.parse(MAIN_SOURCE.read_text(encoding="utf-8"), filename=str(MAIN_SOURCE))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {
        "urllib": urllib,
        "api_json": api,
        "MANGADEX_SOURCE": MangaDexSource(api),
        "collect_titles": collect_titles,
        "choose_preferred_title": choose_preferred_title,
        "_iter_aggregate_nodes": _iter_aggregate_nodes,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(MAIN_SOURCE), "exec"), namespace)
    return namespace


class MangaDexSourceBoundaryTests(unittest.TestCase):
    def test_valid_mangadex_url_parsing(self):
        source = MangaDexSource(lambda _url, **_kwargs: None)
        self.assertIsInstance(source, SourceAdapter)
        self.assertEqual(source.parse_manga_ref(MANGA_URL), MANGA_ID)
        self.assertEqual(source.parse_manga_ref(MANGA_URL + "/example-title"), MANGA_ID)

    def test_invalid_mangadex_url_parsing(self):
        source = MangaDexSource(lambda _url, **_kwargs: None)
        self.assertIsNone(source.parse_manga_ref("https://example.test/title/not-a-uuid"))
        self.assertIsNone(source.parse_manga_ref(""))
        self.assertIsNone(source.parse_manga_ref(None))

    def test_metadata_loading_through_adapter(self):
        api = FixtureAPI(metadata=load_fixture("metadata_full.json"))
        metadata = MangaDexSource(api).get_manga(MANGA_URL, preferred="ja")
        self.assertEqual(metadata["uuid"], MANGA_ID)
        self.assertEqual(metadata["title"], "原題")
        self.assertEqual(metadata["author"], "Author Name")
        self.assertEqual(metadata["available_languages"], ["en", "fr", "es-la"])

    def test_adapter_preserves_invalid_reference_error(self):
        source = MangaDexSource(lambda _url, **_kwargs: None)
        with self.assertRaisesRegex(
            ValueError,
            r"Paste a MangaDex title-page URL, for example https://mangadex.org/title/\.\.\.",
        ):
            source.get_manga("invalid", preferred="en")

    def test_compatibility_wrappers_match_adapter(self):
        fixture = load_fixture("metadata_full.json")
        wrapper_api = FixtureAPI(metadata=fixture)
        adapter_api = FixtureAPI(metadata=fixture)
        functions = load_mangadex_functions(wrapper_api)
        adapter = MangaDexSource(adapter_api)

        self.assertEqual(functions["manga_uuid"](MANGA_URL), adapter.parse_manga_ref(MANGA_URL))
        self.assertEqual(
            functions["load_manga_metadata"](MANGA_URL, preferred="fr"),
            adapter.get_manga(MANGA_URL, preferred="fr"),
        )


class MetadataCharacterizationTests(unittest.TestCase):
    def test_metadata_normalizes_preferred_title_author_languages_and_cover(self):
        api = FixtureAPI(metadata=load_fixture("metadata_full.json"))
        functions = load_mangadex_functions(api)

        metadata = functions["load_manga_metadata"](MANGA_URL, preferred="ja")

        self.assertEqual(metadata["uuid"], MANGA_ID)
        self.assertEqual(metadata["title"], "原題")
        self.assertEqual(metadata["author"], "Author Name")
        self.assertEqual(metadata["available_languages"], ["en", "fr", "es-la"])
        self.assertEqual(metadata["original_language"], "ja")
        self.assertEqual(
            metadata["main_cover_url"],
            f"https://uploads.mangadex.org/covers/{MANGA_ID}/main-cover.jpg",
        )
        self.assertEqual(
            [(row["language"], row["title"]) for row in metadata["titles"]],
            [
                ("ja", "原題"),
                ("en", "English Title"),
                ("fr", "Titre français"),
                ("en", "Alternate English Title"),
            ],
        )

    def test_metadata_uses_english_fallback(self):
        api = FixtureAPI(metadata=load_fixture("metadata_full.json"))
        functions = load_mangadex_functions(api)
        metadata = functions["load_manga_metadata"](MANGA_URL, preferred="de")
        self.assertEqual(metadata["title"], "English Title")

    def test_metadata_tolerates_missing_optional_fields(self):
        api = FixtureAPI(metadata=load_fixture("metadata_missing_optional.json"))
        functions = load_mangadex_functions(api)
        metadata = functions["load_manga_metadata"](MANGA_URL, preferred="fr")
        self.assertEqual(metadata["title"], "唯一の題名")
        self.assertEqual(metadata["author"], "")
        self.assertEqual(metadata["available_languages"], [])
        self.assertEqual(metadata["original_language"], "")
        self.assertEqual(metadata["main_cover_url"], "")


class DownloadPlanCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.aggregate = load_fixture("aggregate_plan.json")
        self.feed_pages = {
            0: load_fixture("chapter_feed_page_1.json"),
            500: load_fixture("chapter_feed_page_2.json"),
        }

    def plan(self, *, aggregate=None, feed_pages=None, failures=()):
        api = FixtureAPI(
            aggregate=self.aggregate if aggregate is None else aggregate,
            feed_pages=self.feed_pages if feed_pages is None else feed_pages,
            failures=failures,
        )
        functions = load_mangadex_functions(api)
        return functions["fetch_download_plan"](MANGA_URL, "en")

    def test_aggregate_and_feed_are_unioned_and_sorted(self):
        plan = self.plan()
        self.assertEqual(plan["volumes"], [1.0, 2.5, 3.0, 10.0])
        self.assertEqual(
            plan["chapters_by_volume"],
            {1.0: 2, 2.5: 2, 3.0: 1, 10.0: 1},
        )
        self.assertEqual(plan["bonus_chapters"], 2)
        self.assertEqual(plan["aggregate_error"], "")
        self.assertEqual(plan["feed_error"], "")

    def test_aggregate_only_success(self):
        plan = self.plan(feed_pages={0: {"data": []}})
        self.assertEqual(plan["volumes"], [2.5, 3.0, 10.0])
        self.assertEqual(plan["bonus_chapters"], 2)

    def test_feed_only_success(self):
        plan = self.plan(aggregate={"volumes": {}})
        self.assertEqual(plan["volumes"], [1.0, 2.5, 10.0])
        self.assertEqual(plan["bonus_chapters"], 1)

    def test_partial_aggregate_failure_keeps_feed_plan_and_error(self):
        plan = self.plan(failures={"aggregate"})
        self.assertEqual(plan["volumes"], [1.0, 2.5, 10.0])
        self.assertEqual(plan["aggregate_error"], "fixture aggregate failure")
        self.assertEqual(plan["feed_error"], "")

    def test_partial_feed_failure_keeps_aggregate_plan_and_error(self):
        plan = self.plan(failures={"feed"})
        self.assertEqual(plan["volumes"], [2.5, 3.0, 10.0])
        self.assertEqual(plan["aggregate_error"], "")
        self.assertEqual(plan["feed_error"], "fixture feed failure")

    def test_both_sources_failing_raises_combined_error(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"Aggregate: fixture aggregate failure \| Feed: fixture feed failure",
        ):
            self.plan(failures={"aggregate", "feed"})


class ChapterDiscoveryCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.api = FixtureAPI(
            feed_pages={
                0: load_fixture("chapter_feed_page_1.json"),
                500: load_fixture("chapter_feed_page_2.json"),
            }
        )
        self.functions = load_mangadex_functions(self.api)

    def test_chapters_preserve_api_order_and_normalize_records(self):
        chapters = self.functions["fetch_chapter_entries"](MANGA_URL, "en")
        self.assertEqual(
            [(row["volume"], row["chapter"]) for row in chapters],
            [(1.0, "1"), (1.0, "2"), (10.0, "10"), (2.5, "12.5"), (None, "special")],
        )
        self.assertEqual([row["id"] for row in chapters], [
            "chapter-1", "chapter-2", "chapter-10", "chapter-12-5", "standalone-special"
        ])
        self.assertEqual(chapters[3]["pages"], 25)

    def test_duplicate_and_external_chapters_are_excluded(self):
        chapters = self.functions["fetch_chapter_entries"](MANGA_URL, "en")
        ids = {row["id"] for row in chapters}
        self.assertNotIn("duplicate-1", ids)
        self.assertNotIn("external-3", ids)

    def test_explicit_volume_range_excludes_other_and_standalone_chapters(self):
        chapters = self.functions["fetch_chapter_entries"](
            MANGA_URL, "en", start_volume=2, end_volume=3
        )
        self.assertEqual([(row["volume"], row["chapter"]) for row in chapters], [(2.5, "12.5")])

    def test_feed_pagination_advances_by_returned_row_count(self):
        self.functions["fetch_chapter_entries"](MANGA_URL, "en")
        offsets = [
            int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["offset"][0])
            for url in self.api.urls
        ]
        self.assertEqual(offsets, [0, 500])


class VolumeCoverCharacterizationTests(unittest.TestCase):
    def test_covers_normalize_volumes_and_last_duplicate_wins(self):
        api = FixtureAPI(covers=load_fixture("volume_covers.json"))
        functions = load_mangadex_functions(api)
        covers = functions["fetch_volume_covers"](MANGA_URL)
        prefix = f"https://uploads.mangadex.org/covers/{MANGA_ID}/"
        self.assertEqual(
            covers,
            {
                1.0: prefix + "volume-1-new.jpg",
                2.5: prefix + "volume-2-5.png",
                None: prefix + "no-volume.jpg",
            },
        )


if __name__ == "__main__":
    unittest.main()
