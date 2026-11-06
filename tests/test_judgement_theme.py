"""Pure-Python design-token/package contracts; geometry lives in the Qt smoke."""
import json
from pathlib import Path
import unittest

from calibre_plugins.manganana.presentation import mangaanka_theme as theme
from tools.build_plugin import files_to_package, syntax_check

ROOT = Path(__file__).resolve().parents[1]


class JudgementThemeTests(unittest.TestCase):
    def test_canonical_brand_tokens_and_scales(self):
        tokens = json.loads((ROOT/'docs/ui/mangaanka.tokens.json').read_text(encoding='utf-8'))
        names = ('DEEP_OCEAN', 'MIDNIGHT_BLUE', 'STORM_BLUE', 'SEA_GREEN',
                 'BRIGHT_SEAFOAM', 'DEEP_TEAL', 'INDIGO_DEPTH', 'OFF_WHITE',
                 'MIST_GRAY', 'LIGHTHOUSE_RED', 'SOFT_BEACON_WHITE')
        self.assertEqual({getattr(theme, name) for name in names}, set(tokens['color']['brand'].values()))
        self.assertEqual(theme.SPACING, tuple(int(v[:-2]) for v in tokens['spacing'].values()))
        self.assertEqual(theme.RADII, tuple(int(v[:-2]) for k, v in tokens['radius'].items() if k != 'pill'))
        self.assertEqual(theme.DISABLED_BG, tokens['color']['semantic']['disabledBg'])
        self.assertEqual(theme.DISABLED_TEXT, tokens['color']['semantic']['disabledText'])

    def test_shared_styles_cover_control_states(self):
        qss = theme.stylesheet()
        for control in ('QCheckBox', 'QRadioButton', 'QSlider', 'QComboBox', 'QLineEdit',
                        'QAbstractItemView', 'QHeaderView', 'QScrollBar', 'QProgressBar'):
            self.assertIn(control, qss)
        for state in (':hover', ':pressed', ':focus', ':checked', ':disabled'):
            self.assertIn(state, qss)
        self.assertNotIn('#FF6740', qss)
        self.assertNotIn('url(', qss, 'No platform or temporary-file indicator dependency')
        self.assertIn('background:#66B7A8; color:#08131D;', qss)

    def test_asset_is_packaged_from_the_authoritative_original(self):
        files = {name: source for source, name in files_to_package(ROOT)}
        self.assertEqual(files['images/mangaanka-app-icon.png'], ROOT/'docs/ui/mangaanka-app-icon.png')
        self.assertNotEqual(files['images/mangaanka-app-icon.png'], files['images/icon.png'])
        for name in ('presentation/mangaanka_theme.py', 'presentation/mangaanka_widgets.py'):
            self.assertIn(name, files)
        self.assertTrue(files['images/mangaanka-app-icon.png'].is_file())
        syntax_check(ROOT)

    def test_shared_shell_does_not_own_workflow_transitions(self):
        widgets = (ROOT/'presentation/mangaanka_widgets.py').read_text(encoding='utf-8')
        self.assertIn("setAccessibleName('MangaAnkā')", widgets)
        self.assertIn("QLabel('From jgog')", widgets)
        self.assertNotIn('mangaanka-calibre-icon', widgets)
        self.assertIn('stage_requested.emit(stage)', widgets)
        self.assertNotIn('workflow_state', widgets)
        self.assertIn('self.workspace.setWidget(widget)', widgets)
        self.assertIn('self.layout.addWidget(self.footer)', widgets)

    def test_native_check_and_combo_keep_qt_control_semantics(self):
        widgets = (ROOT/'presentation/mangaanka_widgets.py').read_text(encoding='utf-8')
        self.assertIn('class MangaAnkaCheckBox(QCheckBox):', widgets)
        self.assertIn('class MangaAnkaComboBox(QComboBox):', widgets)
        self.assertIn('SE_CheckBoxIndicator', widgets)
        self.assertIn('SC_ComboBoxArrow', widgets)
        self.assertNotIn('def mousePressEvent', widgets)
        self.assertNotIn('def keyPressEvent', widgets)

    def test_qt_smoke_runner_enables_assertions(self):
        runner = (ROOT/'tools/run_qt_checks.py').read_text(encoding='utf-8')
        self.assertIn('optimize=0', runner)

    def test_trending_demo_does_not_imply_personalization(self):
        html = (ROOT/'docs/ui/prototype/index.html').read_text(encoding='utf-8')
        self.assertIn('>Trending</h3>', html)
        self.assertNotIn('Recommended for you', html)


if __name__ == '__main__':
    unittest.main()
