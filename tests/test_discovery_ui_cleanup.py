"""Focused contracts for source-neutral discovery copy and provider badges."""

from pathlib import Path
import unittest

from PIL import Image

from provider_branding import (
    DEFAULT_PROVIDER_BRAND,
    provider_badge_spec,
    source_badge_specs,
)
from tools.build_plugin import files_to_package


ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
BRANDING = (ROOT / 'provider_branding.py').read_text(encoding='utf-8')
CANONICAL = (ROOT / 'canonical_identity.py').read_text(encoding='utf-8')

EXPECTED = {
    'mangadex': ('MangaDex', '#FF6740', 'images/favicon_mangadex_org_32x32.png'),
    'mangapill': ('MangaPill', '#0070F3', 'images/favicon_mangapill_com_32x32.png'),
    'weebcentral': ('WeebCentral', '#454EA7', 'images/favicon_weebcentral_com_32x32.png'),
}


class DiscoveryUiCleanupTests(unittest.TestCase):
    def test_provider_branding_uses_full_names_exact_colors_and_local_icons(self):
        for source_id, (name, accent, icon_path) in EXPECTED.items():
            with self.subTest(source_id=source_id):
                spec = provider_badge_spec(source_id, '')
                self.assertEqual(name, spec['text'])
                self.assertEqual(accent, spec['accent_color'])
                self.assertEqual(icon_path, spec['icon_path'])

    def test_source_badge_specs_are_deduplicated_and_source_keyed(self):
        specs = source_badge_specs(
            ('MangaDex', 'MangaPill', 'MangaDex'),
            ('mangadex', 'mangapill', 'mangadex'),
        )
        self.assertEqual([spec['text'] for spec in specs], ['MangaDex', 'MangaPill'])
        self.assertEqual([spec['source_id'] for spec in specs], ['mangadex', 'mangapill'])

    def test_unknown_provider_fallback_is_neutral_and_text_only(self):
        spec = provider_badge_spec('future-source', 'Future Source')
        self.assertEqual(DEFAULT_PROVIDER_BRAND.accent_color, spec['accent_color'])
        self.assertEqual('Future Source', spec['text'])
        self.assertEqual('', spec['icon_path'])
        self.assertNotIn('fallback_glyph', spec)
        self.assertNotIn('icon_url', spec)

    def test_provider_branding_is_presentation_only(self):
        for forbidden in (
            'canonical_identity', 'relevance', 'ranking', 'inventory',
            'urllib', 'requests', 'http://', 'https://',
        ):
            self.assertNotIn(forbidden, BRANDING)
        self.assertNotIn('provider_branding', CANONICAL)

    def test_authoritative_favicons_exist_are_32_square_and_are_packaged(self):
        packaged = {archive_path for _source, archive_path in files_to_package(ROOT)}
        for _source_id, (_name, _accent, icon_path) in EXPECTED.items():
            with self.subTest(icon_path=icon_path):
                path = ROOT / icon_path
                self.assertTrue(path.is_file())
                with Image.open(path) as image:
                    self.assertEqual((32, 32), image.size)
                    self.assertIn('A', image.getbands())
                self.assertIn(icon_path, packaged)

    def test_icon_loading_is_local_only_and_missing_icons_are_text_only(self):
        self.assertIn('raw = get_resources(path)', MAIN)
        self.assertIn('asset.is_file()', MAIN)
        self.assertIn('Qt.AspectRatioMode.KeepAspectRatio', MAIN)
        self.assertIn('Qt.TransformationMode.SmoothTransformation', MAIN)
        self.assertIn('ICON_SIZE = 16', MAIN)
        self.assertNotIn('fallback_glyph', MAIN)
        self.assertNotIn('favicon.ico', MAIN)
        self.assertNotIn('urlopen', BRANDING)

    def test_badges_keep_dark_outlined_manganana_style_and_full_text_width(self):
        self.assertIn('class ProviderBadgeWidget(QFrame):', MAIN)
        self.assertIn('background:#211E1D', MAIN)
        self.assertIn('border:1px solid {accent}', MAIN)
        self.assertIn('QGraphicsDropShadowEffect(self)', MAIN)
        self.assertIn('text.setMinimumWidth(text.sizeHint().width())', MAIN)
        self.assertIn('QSizePolicy.Policy.Minimum', MAIN)
        for monogram in ("'MD'", "'MP'", "'WC'"):
            self.assertNotIn(monogram, MAIN + BRANDING)

    def test_unresolved_search_hits_do_not_claim_usable_provider_sources(self):
        self.assertIn("unresolved = QLabel('Checking sources…')", MAIN)
        self.assertIn('title, author, badge=badge, parent=self.search_results', MAIN)
        self.assertNotIn('title, author, group.source_names, group.source_ids', MAIN)

    def test_discovery_copy_is_provider_neutral_and_browse_mangadex_is_removed(self):
        self.assertIn("setPlaceholderText('Search manga sources...')", MAIN)
        self.assertIn("QLabel('Already have a manga link?')", MAIN)
        self.assertIn("QLabel('Paste a supported manga link.')", MAIN)
        self.assertIn("setPlaceholderText('Paste a supported manga link...')", MAIN)
        self.assertIn("QCheckBox('Use source volume cover in Calibre metadata')", MAIN)
        self.assertNotIn('Search MangaDex and MangaPill...', MAIN)
        self.assertNotIn('Have a title link?', MAIN)
        self.assertNotIn('Paste a MangaDex or MangaPill title URL directly.', MAIN)
        self.assertNotIn('Browse MangaDex', MAIN)
        self.assertNotIn('Load MangaDex metadata first.', MAIN)


if __name__ == '__main__':
    unittest.main()
