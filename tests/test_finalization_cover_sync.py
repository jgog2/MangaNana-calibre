"""Cover invalidation keys and preview-only presentation contracts."""
import ast
from pathlib import Path
import unittest
from calibre_plugins.manganana.books.imaging.cover_rendering import badge_text, cover_title
from tests.test_output_series_metadata import metadata

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT/'books/output/finalization_covers.py').read_text(encoding='utf-8'))
namespace = dict(badge_text=badge_text, cover_title=cover_title, effective_output_metadata=metadata.effective_output_metadata)
exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'cover_job'],
                        type_ignores=[]), 'books/output/finalization_covers.py', 'exec'), namespace)
cover_job = namespace['cover_job']


class CoverSynchronizationTests(unittest.TestCase):
    def test_numbered_pdf_changes_generated_and_stamp_keys_but_not_keep(self):
        row = dict(kind='import', volume=None, title='PDF', book=dict(id='pdf', identity=('file', 1, 2)))
        changed = dict(row, output_overrides={'series_index': 67})
        for mode in ('generate', 'stamp'):
            before, after = self.job(mode, row=row), self.job(mode, row=changed)
            self.assertEqual(after['options']['volume'], 67)
            self.assertEqual(after['key'][-1], '67')
            self.assertNotEqual(before['key'], after['key'])
        self.assertEqual(self.job('keep', row=row)['key'], self.job('keep', row=changed)['key'])

    def test_source_volume_14_override_21_reaches_stamp_and_cache_key(self):
        source = dict(kind='volume',volume=14,title='Source',series='Series')
        override = dict(source,output_overrides={'series_index':21})
        original = self.job('stamp',row=source)
        updated = self.job('stamp',row=override)
        self.assertEqual(updated['options']['volume'],21)
        self.assertEqual(updated['key'][-1],'21')
        self.assertNotEqual(updated['key'],original['key'])
        self.assertEqual(override['volume'],14)

    def job(self, mode='generate', **changes):
        values = dict(row=dict(kind='volume', volume=1), mode=mode, include=True,
                      zero_pad=True, title='Applied title', series='Series', source_id='source', cover_url='one.png')
        values.update(changes)
        return cover_job(**values)

    def test_generated_cover_keys_include_authoritative_title_and_individual_number(self):
        base = self.job()['key']
        self.assertNotEqual(base, self.job(title='New title')['key'])
        self.assertNotEqual(base, self.job(row=dict(kind='volume', volume=2))['key'])
        self.assertNotEqual(base, self.job(zero_pad=False)['key'])
        self.assertEqual(base, self.job(include=False, cover_url='unrelated.png')['key'])

    def test_keep_does_not_regenerate_for_metadata_or_padding(self):
        self.assertEqual(self.job('keep')['key'], self.job('keep', title='Changed', series='Changed', zero_pad=False)['key'])
        self.assertNotEqual(self.job('keep')['key'], self.job('keep', include=False)['key'])

    def test_stamp_ignores_title_and_disabled_inclusion_but_tracks_artwork(self):
        self.assertEqual(self.job('stamp')['key'], self.job('stamp', title='Changed', include=False)['key'])
        self.assertNotEqual(self.job('stamp')['key'], self.job('stamp', cover_url='two.png')['key'])

    def test_number_keys_follow_the_rendered_badge(self):
        standalone = dict(kind='standalone', volume=None)
        self.assertEqual(self.job(row=standalone)['key'], self.job(row=standalone, zero_pad=False)['key'])
        chapter = dict(kind='chapter', volume=16, chapter={'chapter':'103'})
        job = self.job(row=chapter)
        self.assertEqual(job['options']['chapter_number'], 103)
        self.assertEqual(job['key'][-1], '103')

    def test_imports_use_each_books_applied_metadata_and_file_identity(self):
        row = dict(kind='import', title='Book one', series='Collection', volume=3,
                   book=dict(id='book', identity=('file', 123, 456)))
        job = self.job(row=row)
        self.assertEqual(job['options']['title'], 'Book one')
        self.assertEqual(job['options']['volume'], 3)
        self.assertNotEqual(job['key'], self.job(row={**row, 'title':'Book two', 'volume':4})['key'])
        keep = self.job('keep', row=row)
        changed = {**row, 'book':dict(id='book', identity=('file', 789, 456))}
        self.assertNotEqual(keep['key'], self.job('keep', row=changed)['key'])

    def test_preview_observes_existing_cover_without_work_or_row_mutation(self):
        main = (ROOT/'app/main.py').read_text(encoding='utf-8')
        preview = main[main.index('    def _show_cover_preview'):main.index('    def _planned_output_cover_url')]
        self.assertIn("row.get('cover_thumbnail')", preview)
        for forbidden in ('Worker(', 'render_cover(', '_refresh_output_covers(', 'setCellWidget(', 'continue_preview('):
            self.assertNotIn(forbidden, preview)

    def test_initial_ready_and_applied_metadata_schedule_cover_updates(self):
        main = (ROOT/'app/main.py').read_text(encoding='utf-8')
        for start, end in (('    def on_preview_ready', '    def _preview_use_toggled'),
                           ('    def apply_metadata', '    def add_log')):
            section = main[main.index(start):main.index(end)]
            self.assertIn('self._refresh_output_covers()', section)


if __name__ == '__main__':
    unittest.main()
