"""Unit tests for the generic source registration and URL recognition boundary."""

import unittest
import ast
from pathlib import Path

from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.providers.source_registry import SourceRegistry


MANGA_ID = "12345678-1234-1234-1234-123456789abc"
MANGA_URL = f"https://mangadex.org/title/{MANGA_ID}/example"


class SourceRegistryTests(unittest.TestCase):
    def test_application_registers_all_five_sources_without_url_collisions(self):
        from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
        from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
        from calibre_plugins.manganana.providers.mangak_source import MangaKSource
        from calibre_plugins.manganana.providers.atsu_source import AtsuSource
        from calibre_plugins.manganana.providers.source_policy import enabled_sources

        namespace = {cls.__name__: cls for cls in (
            SourceRegistry, MangaDexSource, MangaPillSource, WeebCentralSource, MangaKSource, AtsuSource)}
        root = Path(__file__).resolve().parent.parent
        tree = ast.parse((root / 'app/main.py').read_text(encoding='utf-8'))
        names = {'MANGADEX_SOURCE', 'MANGAPILL_SOURCE', 'WEEBCENTRAL_SOURCE',
                 'MANGAK_SOURCE', 'ATSU_SOURCE', 'SOURCE_REGISTRY'}
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
        exec(compile(ast.Module(body=assignments, type_ignores=[]), 'registry assignments', 'exec'), namespace)
        registry = namespace['SOURCE_REGISTRY']
        self.assertEqual(['mangadex', 'mangapill', 'weebcentral', 'mangak', 'atsu'],
                         [source.source_id for source in registry.all()])
        for source_id, url in (
            ('mangadex', MANGA_URL), ('mangapill', 'https://mangapill.com/manga/5674/example'),
            ('weebcentral', 'https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/example'),
            ('mangak', 'https://mangak.io/one-piece'), ('atsu', 'https://atsu.moe/manga/Xqitk'),
        ):
            self.assertEqual(source_id, registry.identify(url).source.source_id)
        prefs = {'source_enabled': {'mangak': False, 'atsu': False}}
        self.assertEqual(['mangadex', 'mangapill', 'weebcentral'],
                         [source.source_id for source in enabled_sources(registry, prefs)])

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
