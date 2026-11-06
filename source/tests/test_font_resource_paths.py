"""Bundled font identity must not depend on extracted profile path length."""
import ast
from pathlib import Path
import shutil
import tempfile
import unittest
from qt.core import QFontDatabase,QFont

ROOT=Path(__file__).resolve().parents[1]


class FontPaths(unittest.TestCase):
    def test_production_loader_keeps_geist_on_long_resource_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            font_root=Path(directory)/('a'*70)/('b'*70)/('c'*70)/'fonts'
            font_root.mkdir(parents=True)
            for name in ('Regular','SemiBold','Bold'):
                shutil.copyfile(ROOT/f'assets/ui/fonts/Geist-{name}.ttf',font_root/f'Geist-{name}.ttf')
            tree=ast.parse((ROOT/'presentation/choose_manga_design.py').read_text(encoding='utf8'))
            method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review_font')
            namespace=dict(QFontDatabase=QFontDatabase,QFont=QFont,FONT_ROOT=font_root,_font_family=None)
            exec(compile(ast.Module(body=[method],type_ignores=[]),'production review_font','exec'),namespace)
            self.assertGreater(len(str(font_root/'Geist-Regular.ttf')),260)
            font=namespace['review_font']()
            self.assertEqual('Geist',font.families()[0]);self.assertEqual(15,font.pixelSize())
            self.assertEqual(font.families(),namespace['review_font']().families())


if __name__=='__main__':unittest.main()
