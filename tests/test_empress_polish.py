"""Narrow preset label/value, density and exact vendored-icon contracts."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from image_processing import ProcessingSettings
from processing_presets import BUILTIN_PRESETS, BUILTIN_PRESETS_BY_ID, matching_preset, settings_to_payload


ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
SVG=ROOT/'images'/'tabler-book.svg'


class EmpressPolishTests(unittest.TestCase):
    def test_reviewed_builtin_names_ids_and_values(self):
        self.assertEqual(('Original','B&W Manga','High Contrast B&W','Soft Grayscale','Color Enhancement'),
                         tuple(p.name for p in BUILTIN_PRESETS))
        high=BUILTIN_PRESETS_BY_ID['high_contrast_manga']
        self.assertEqual('high_contrast_manga',high.preset_id)
        self.assertEqual(high,matching_preset(high.settings))
        color=BUILTIN_PRESETS_BY_ID['color_enhancement'].settings
        self.assertEqual(ProcessingSettings(contrast=1.08,saturation=1.25,sharpness=1.10),color)
        self.assertEqual(ProcessingSettings(),BUILTIN_PRESETS_BY_ID['original'].settings)

    def test_screen_emulation_absent_from_preset_schema(self):
        payload=settings_to_payload(ProcessingSettings())
        self.assertFalse(any('screen' in key or 'device' in key for key in payload))

    def test_exact_tabler_book_asset(self):
        root=ET.fromstring(SVG.read_text(encoding='utf-8'))
        self.assertEqual('36',root.attrib['width'])
        self.assertEqual('36',root.attrib['height'])
        self.assertEqual('0 0 24 24',root.attrib['viewBox'])
        self.assertEqual({'fill':'none','stroke':'#FF6740','stroke-width':'1.4',
                          'stroke-linecap':'round','stroke-linejoin':'round'},
                         {key:root.attrib[key] for key in ('fill','stroke','stroke-width','stroke-linecap','stroke-linejoin')})
        expected=('M3 19a9 9 0 0 1 9 0a9 9 0 0 1 9 0','M3 6a9 9 0 0 1 9 0a9 9 0 0 1 9 0',
                  'M3 6l0 13','M12 6l0 13','M21 6l0 13')
        self.assertEqual(expected,tuple(node.attrib['d'] for node in root))

    def test_layout_density_and_icons_are_locally_scoped(self):
        self.assertIn('cv.setContentsMargins(18,12,18,12); cv.setSpacing(7)',MAIN)
        self.assertRegex(MAIN,r'QPushButton#layoutChoice \{\{[^\n]+min-height:62px; max-height:62px;')
        self.assertIn("self.landscape_btn=LeftShiftIconButton('LANDSCAPE\\nPaired Pages',icon_left_shift=5)",MAIN)
        self.assertIn("self.landscape_btn.setIconSize(QSize(36,36))",MAIN)
        self.assertIn("self.portrait_btn.setIconSize(QSize(38,28))",MAIN)
        self.assertIn("get_resources('images/tabler-book.svg')",MAIN)
        shifted=MAIN[MAIN.index('class LeftShiftIconButton(QPushButton):'):MAIN.index('class VolumeRowWidget(QFrame):')]
        self.assertIn('painter.translate(-shift / 2.0, 0)',shifted)
        self.assertIn('option.iconSize = QSize(icon_size.width() + shift, icon_size.height())',shifted)
        portrait=MAIN[MAIN.index('def _layout_icon('):MAIN.index('def build_ui(')]
        self.assertIn('painter.drawRoundedRect(13,3,20,27,2,2)',portrait)

    def test_preset_menu_has_no_builtin_header(self):
        refresh=MAIN[MAIN.index('def _refresh_processing_presets(self):'):MAIN.index('def _sync_processing_preset(self, settings=None):')]
        self.assertNotIn("'BUILT-IN'",refresh)
        self.assertIn('for preset in BUILTIN_PRESETS:',refresh)
        self.assertIn("if self._user_processing_presets:",refresh)
        self.assertIn("self.processing_preset.addItem('MY PRESETS',None)",refresh)

    def test_notice_and_package_manifest_include_asset(self):
        notice=(ROOT/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
        build=(ROOT/'tools'/'build_plugin.py').read_text(encoding='utf-8')
        self.assertIn('Copyright (c) 2020-2026 Paweł Kuna',notice)
        self.assertIn('images/tabler-book.svg',build)
        self.assertIn('THIRD_PARTY_NOTICES.md',build)


if __name__=='__main__': unittest.main()
