"""Toolbar presentation changes must preserve the Calibre action identity."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from tools.build_plugin import files_to_package

ROOT = Path(__file__).resolve().parents[1]


class JudgementActionTests(unittest.TestCase):
    def load_action(self):
        actions = types.ModuleType('calibre.gui2.actions')
        actions.InterfaceAction = type('InterfaceAction', (), {})
        gui2 = types.ModuleType('calibre.gui2'); gui2.error_dialog = Mock()
        with patch.dict(sys.modules, {'calibre.gui2': gui2, 'calibre.gui2.actions': actions}):
            spec = importlib.util.spec_from_file_location('judgement_action_test', ROOT/'ui.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_visible_name_and_icon_keep_stable_action_id(self):
        module = self.load_action()
        self.assertEqual(module.MangaNanaAction.name, 'MangaNana')
        self.assertEqual(module.MangaNanaAction.action_spec[:2],
                         ('MangaAnkā', 'images/mangaanka-calibre-icon.png'))
        action = module.MangaNanaAction(); action.qaction = Mock()
        icon = Mock(); icon.isNull.return_value = False
        module.get_icons = Mock(return_value=icon)
        action.genesis()
        module.get_icons.assert_called_once_with('images/mangaanka-calibre-icon.png', 'MangaNana')
        action.qaction.setIcon.assert_called_once_with(icon)
        action.qaction.triggered.connect.assert_called_once_with(action.show_dialog)

    def test_toolbar_resource_is_dedicated_original(self):
        files = {name: path for path, name in files_to_package(ROOT)}
        self.assertEqual(files['images/mangaanka-calibre-icon.png'], ROOT/'docs/ui/mangaanka-calibre-icon.png')
        self.assertTrue(files['images/mangaanka-calibre-icon.png'].is_file())
        self.assertNotEqual(files['images/mangaanka-app-icon.png'], files['images/mangaanka-calibre-icon.png'])

    def test_current_public_branding_and_stable_internal_plugin_identity(self):
        main = (ROOT/'app/main.py').read_text(encoding='utf-8')
        self.assertIn("VL_NAME = 'MangaAnkā'", main)
        self.assertIn("VL_TAG = 'MangaAnkā'", main)
        plugin = (ROOT/'__init__.py').read_text(encoding='utf-8')
        self.assertIn("name = 'MangaNana'", plugin)


if __name__ == '__main__':
    unittest.main()
