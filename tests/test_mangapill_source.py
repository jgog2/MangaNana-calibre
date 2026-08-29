"""Offline characterization tests for the MangaPill source adapter."""

from pathlib import Path
import unittest

from mangadex_source import MangaDexSource
from mangapill_source import MangaPillSource
from source_adapter import SourceAdapter
from source_registry import SourceRegistry
from source_coordinator import count_chapter_pages


FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANGA_URL = "https://mangapill.com/manga/5674/one-piece-episode-a"
CHAPTER_URL = "https://mangapill.com/chapters/5674-10001000/one-piece-episode-a-chapter-1"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FixtureHTML:
    def __init__(self, *, search="mangapill_search.html", title="mangapill_title.html",
                 chapter="mangapill_chapter.html"):
        self.search = search
        self.title = title
        self.chapter = chapter
        self.urls = []

    def __call__(self, url, **_kwargs):
        self.urls.append(url)
        if "/search?" in url:
            return fixture(self.search)
        if "/chapters/" in url:
            return fixture(self.chapter)
        if "/manga/" in url:
            return fixture(self.title)
        raise AssertionError(f"Unexpected fixture URL: {url}")


class MangaPillSourceTests(unittest.TestCase):
    def setUp(self):
        self.html = FixtureHTML()
        self.source = MangaPillSource(self.html, lambda _url, **_kwargs: b"image")

    def test_registration_metadata_and_lookup(self):
        registry = SourceRegistry((MangaDexSource(lambda _url, **_kwargs: None), self.source))
        self.assertIsInstance(self.source, SourceAdapter)
        self.assertIs(registry.get("mangapill"), self.source)
        self.assertEqual(self.source.display_name, "MangaPill")
        self.assertEqual(self.source.domains, ("mangapill.com", "www.mangapill.com"))
        self.assertTrue(self.source.enabled_by_default)
        self.assertNotIn("volumes", self.source.capabilities)

    def test_direct_url_recognition_through_registry(self):
        match = SourceRegistry((self.source,)).identify(MANGA_URL)
        self.assertIs(match.source, self.source)
        self.assertEqual(match.reference, "5674")
        self.assertIsNone(SourceRegistry((self.source,)).identify(
            "https://example.test/manga/5674/lookalike"
        ))

    def test_chapter_url_is_recognized_and_resolves_to_parent_manga(self):
        match = SourceRegistry((self.source,)).identify(CHAPTER_URL)
        self.assertIs(match.source, self.source)
        self.assertEqual(match.reference, CHAPTER_URL)
        self.assertEqual(self.source.resolve_manga_ref(CHAPTER_URL), "5674")
        metadata = self.source.get_manga(CHAPTER_URL)
        self.assertEqual(metadata["uuid"], "5674")
        self.assertEqual(metadata["source_url"], "https://mangapill.com/manga/5674")

    def test_foreign_domain_chapter_lookalike_is_rejected(self):
        lookalike = "https://example.test/chapters/5674-10001000/example-chapter-1"
        self.assertIsNone(self.source.parse_manga_ref(lookalike))
        self.assertIsNone(SourceRegistry((self.source,)).identify(lookalike))

    def test_search_normalization(self):
        result = self.source.search("One Piece", limit=12)
        self.assertEqual([row["id"] for row in result["rows"]], ["2", "5674"])
        self.assertEqual(result["rows"][0]["title"], "One Piece")
        self.assertEqual(result["rows"][1]["cover_url"], "https://cdn.example/mangapill/i/5674.jpeg")
        self.assertTrue(result["has_more"])
        self.assertIn("q=One+Piece", self.html.urls[0])

    def test_metadata_and_main_cover_extraction(self):
        metadata = self.source.get_manga(MANGA_URL)
        self.assertEqual(metadata["uuid"], "5674")
        self.assertEqual(metadata["title"], "One Piece: Episode A")
        self.assertEqual(metadata["author"], "")
        self.assertEqual(metadata["available_languages"], ["en"])
        self.assertEqual(metadata["main_cover_url"], "https://cdn.example/mangapill/i/5674.jpeg")
        self.assertEqual(metadata["description"], "A compact fixture description.")

    def test_chapters_are_standalone_and_sorted_numerically(self):
        chapters = self.source.get_chapters(MANGA_URL, "en")
        self.assertEqual([row["chapter"] for row in chapters], ["1", "2", "4.5"])
        self.assertTrue(all(row["volume"] is None for row in chapters))
        self.assertTrue(all(row["pages"] is None for row in chapters))
        self.assertEqual(self.source.get_download_plan(MANGA_URL, "en")["bonus_chapters"], 3)
        self.assertEqual(self.source.get_download_plan(MANGA_URL, "en")["volumes"], [])
        self.assertEqual(self.source.get_chapters(MANGA_URL, "fr"), [])
        self.assertEqual(self.source.get_chapters(MANGA_URL, "en", 1, 2), [])

    def test_multiple_standalone_review_counts_sum_manifests_without_image_bytes(self):
        binary_calls = []
        source = MangaPillSource(self.html, lambda url, **_kwargs: binary_calls.append(url))
        chapters = source.get_chapters(MANGA_URL, "en")
        self.assertEqual(count_chapter_pages(source, chapters), 6)
        self.assertEqual(binary_calls, [])

    def test_page_manifest_extracts_only_ordered_reader_images(self):
        manifest = self.source.get_page_manifest(CHAPTER_URL)
        self.assertEqual(manifest["full"], [
            "https://cdn.example/mangap/5674/chapter-1/1.jpeg",
            "https://cdn.example/mangap/5674/chapter-1/2.jpeg",
        ])
        self.assertEqual(manifest["data_saver"], [])

    def test_binary_retrieval_and_preview_use_full_quality(self):
        self.assertEqual(self.source.fetch_binary("https://cdn.example/page.jpeg"), b"image")
        blob, used_full = self.source.fetch_preview_page("", "https://cdn.example/page.jpeg", 1)
        self.assertEqual(blob, b"image")
        self.assertTrue(used_full)

    def test_malformed_and_unsupported_pages_fail_clearly(self):
        malformed = MangaPillSource(FixtureHTML(title="mangapill_malformed.html", chapter="mangapill_malformed.html"))
        with self.assertRaisesRegex(RuntimeError, "did not contain a title"):
            malformed.get_manga(MANGA_URL)
        with self.assertRaisesRegex(RuntimeError, "did not contain readable images"):
            malformed.get_page_manifest(CHAPTER_URL)
        with self.assertRaisesRegex(RuntimeError, "did not contain a parent manga link"):
            malformed.resolve_manga_ref(CHAPTER_URL)
        with self.assertRaisesRegex(ValueError, "valid MangaPill"):
            self.source.get_manga("https://example.test/manga/5674/example")
        with self.assertRaisesRegex(ValueError, "valid MangaPill chapter"):
            self.source.get_page_manifest("https://example.test/chapters/example")


if __name__ == "__main__":
    unittest.main()
