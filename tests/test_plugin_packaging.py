"""Packaging controls: explicit runtime manifest and local dependency closure."""
from pathlib import Path
import tempfile
import unittest

from tools.build_plugin import PYTHON_FILES, files_to_package, validate_local_imports


class PluginPackagingTests(unittest.TestCase):
    def test_phase8_runtime_and_schema_are_packaged(self):
        root = Path(__file__).resolve().parents[1]
        names = {name for _, name in files_to_package(root)}
        self.assertTrue({'publication/catalog_reader.py', 'publication/catalog_review.py',
                         'catalog_schema_v1.json', 'metadata/references/wikipedia_identity.py'} <= names)
        self.assertFalse(any(name.startswith(('tests/', 'build/')) for name in names))
        self.assertIn('LICENSE', names)
        validate_local_imports(root)

    def test_previous_manifest_is_rejected_with_exact_missing_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        previous = tuple(name for name in PYTHON_FILES if name not in {
            'publication/catalog_reader.py', 'publication/catalog_review.py', 'metadata/references/wikipedia_identity.py'})
        with self.assertRaises(ValueError) as caught:
            validate_local_imports(root, previous)
        self.assertIn('app/main.py imports publication/catalog_review.py', str(caught.exception))
        self.assertIn('publication/publication_freshness.py imports metadata/references/wikipedia_identity.py', str(caught.exception))
        self.assertIn('metadata/references/wikipedia_reference.py imports metadata/references/wikipedia_identity.py', str(caught.exception))

    def check_import(self, source, dependency, include=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app').mkdir()
            (root / 'app/__init__.py').write_text('')
            (root / 'app/main.py').write_text(source, encoding='utf-8')
            (root / (dependency + '.py')).write_text('VALUE = 1', encoding='utf-8')
            files = ('app/__init__.py', 'app/main.py', dependency + '.py') if include else ('app/__init__.py', 'app/main.py')
            if include:
                validate_local_imports(root, files)
            else:
                with self.assertRaisesRegex(ValueError, dependency):
                    validate_local_imports(root, files)

    def test_absolute_plugin_import_missing(self):
        self.check_import('from calibre_plugins.manganana.catalog_review import CatalogReview',
                          'catalog_review')

    def test_relative_dependency_missing(self):
        with self.assertRaisesRegex(ValueError, 'Unconverted relative import'):
            self.check_import('from .catalog_reader import decide', 'catalog_reader', include=True)

    def test_package_member_import_missing(self):
        self.check_import('from calibre_plugins.manganana import catalog_reader', 'catalog_reader')

    def test_standalone_local_fallback_missing(self):
        with self.assertRaisesRegex(ValueError, 'Noncanonical local import'):
            self.check_import('import wikipedia_identity', 'wikipedia_identity', include=True)

    def test_packaged_dependency_passes(self):
        self.check_import('from calibre_plugins.manganana.catalog_reader import decide', 'catalog_reader', include=True)

    def test_external_and_generated_imports_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app').mkdir()
            (root / 'app/__init__.py').write_text('')
            (root / 'app/main.py').write_text(
                'import json\nfrom qt.core import QWidget\nfrom calibre_plugins.manganana.build_info import BUILD_ID',
                encoding='utf-8')
            validate_local_imports(root, ('app/__init__.py', 'app/main.py'))


if __name__ == '__main__':
    unittest.main()
