"""Unit tests for the generic source registration and URL recognition boundary."""

import unittest

from mangadex_source import MangaDexSource
from source_registry import SourceRegistry


MANGA_ID = "12345678-1234-1234-1234-123456789abc"
MANGA_URL = f"https://mangadex.org/title/{MANGA_ID}/example"


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.mangadex = MangaDexSource(lambda _url, **_kwargs: None)
        self.registry = SourceRegistry((self.mangadex,))

    def test_register_and_enumerate_sources(self):
        self.assertEqual(self.registry.all(), (self.mangadex,))
        self.assertEqual(self.mangadex.source_id, "mangadex")
        self.assertEqual(self.mangadex.display_name, "MangaDex")
        self.assertEqual(self.mangadex.domains, ("mangadex.org", "www.mangadex.org"))
        self.assertTrue(self.mangadex.enabled_by_default)

    def test_lookup_by_stable_source_id(self):
        self.assertIs(self.registry.get("mangadex"), self.mangadex)
        self.assertIsNone(self.registry.get("missing"))

    def test_duplicate_source_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate source id: mangadex"):
            self.registry.register(MangaDexSource(lambda _url, **_kwargs: None))

    def test_mangadex_direct_url_recognition(self):
        match = self.registry.identify(MANGA_URL)
        self.assertIsNotNone(match)
        self.assertIs(match.source, self.mangadex)
        self.assertEqual(match.reference, MANGA_ID)

    def test_unsupported_url_returns_no_match(self):
        self.assertIsNone(self.registry.identify("https://example.test/manga/example"))
        self.assertIsNone(self.registry.identify(
            f"https://example.test/title/{MANGA_ID}/lookalike"
        ))
        self.assertIsNone(self.registry.identify(""))
        self.assertIsNone(self.registry.identify(None))


if __name__ == "__main__":
    unittest.main()
