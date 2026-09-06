import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image

from local_import import inspect_book, staged_pages, preview_records, import_plan, validate_identity, inspect_pdf, run_tool
from book_export import comicinfo_for_import, write_book


def png(size=(30, 50), color='red'):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, 'PNG')
    return out.getvalue()


class LocalBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='manganana-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def book(self, name='a.cbz', xml=None):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            for member in ('nested/10.png', 'nested/2.png', '../1.png', '__MACOSX/junk.png', 'nested/.hidden.png'):
                archive.writestr(member, png())
            archive.writestr('readme.txt', 'ignore')
            if xml: archive.writestr('ComicInfo.xml', xml)
        return path

    def test_order_junk_safe_staging_and_cleanup(self):
        book = inspect_book(self.book())
        self.assertEqual(book['pages'], 2)  # dot path traversal is ignored
        with staged_pages(book) as records:
            self.assertEqual([r['page_in_chapter'] for r in records], [1, 2])
            self.assertTrue(all('local_path' in r and 'blob' not in r for r in records))
            self.assertTrue(all(r['chapter_pages'] == 2 for r in records))
            paths = [Path(r['local_path']) for r in records]
            self.assertTrue(all(p.exists() for p in paths))
        self.assertTrue(all(not p.exists() for p in paths))
        self.assertFalse((self.root / '1.png').exists())

    def test_metadata_cover_and_multi_book_preserved(self):
        book = inspect_book(self.book(xml=b'<ComicInfo><Title>A</Title><Series>S</Series><Writer>W</Writer><Number>2.5</Number><Summary>Keep</Summary><Pages><Page Image="1" Type="FrontCover"/></Pages></ComicInfo>'))
        other = inspect_book(self.book('other.cbz'))
        self.assertEqual(book['cover_index'], 1)
        rows = import_plan([book, other])
        self.assertEqual([r['title'] for r in rows], ['A', 'other'])
        self.assertEqual([r['series'] for r in rows], ['S', ''])
        self.assertEqual(rows[0]['volume'], 2.5)
        self.assertEqual(import_plan([book, other], {'author': 'New'})[1]['author'], 'New')
        root = ET.fromstring(comicinfo_for_import(book, rows[0], 1, True))
        self.assertEqual(root.findtext('Summary'), 'Keep')
        self.assertEqual(root.findtext('PageCount'), '1')
        self.assertIsNone(root.find('Pages'))

    def test_malformed_metadata_and_stale_identity(self):
        path = self.book(xml=b'<broken')
        book = inspect_book(path)
        self.assertEqual(book['title'], 'a')
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'): validate_identity(book)

    def test_invalid_containers_and_images(self):
        path = self.root / 'bad.cbz'; path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'corrupt'): inspect_book(path)
        with zipfile.ZipFile(path, 'w') as archive: archive.writestr('notes.txt', 'no images')
        with self.assertRaisesRegex(ValueError, 'no supported image'): inspect_book(path)
        with zipfile.ZipFile(path, 'w') as archive: archive.writestr('1.png', b'broken')
        book = inspect_book(path)
        with self.assertRaisesRegex(ValueError, 'page 1'):
            with staged_pages(book): pass

    def test_preview_detaches_from_disk_and_keeps_cover(self):
        book = inspect_book(self.book())
        records = preview_records(book, limit=1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['chapter_pages'], 2)
        self.assertIn('image', records[0]); self.assertNotIn('local_path', records[0])

    def test_cbz_stream_atomic_and_cancel(self):
        output = self.root / 'out.cbz'
        write_book(output, 'cbz', iter([(0, ('.png', png(), 'INDIVIDUAL'))]), comicinfo=b'<ComicInfo/>')
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ['00001.png', 'ComicInfo.xml'])
            self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist()))
        original = output.read_bytes()
        def cancel(): raise InterruptedError()
        with self.assertRaises(InterruptedError):
            write_book(output, 'cbz', iter([(0, ('.png', png(), 'INDIVIDUAL'))]), check=cancel)
        self.assertEqual(output.read_bytes(), original)
        self.assertFalse(Path(str(output)+'.part').exists())

    def test_natural_nested_order_and_first_cover(self):
        path = self.root / 'ordered.cbz'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('chapter10/1.png', png(color='blue'))
            archive.writestr('chapter2/10.png', png(color='green'))
            archive.writestr('chapter2/2.png', png(color='red'))
        book = inspect_book(path)
        self.assertEqual(book['cover_index'], 0)
        with staged_pages(book) as records:
            colors = []
            for row in records:
                with Image.open(row['local_path']) as image: colors.append(image.getpixel((0, 0)))
            self.assertEqual(colors, [(255, 0, 0), (0, 128, 0), (0, 0, 255)])

    def test_exif_normalized_on_disk(self):
        out = io.BytesIO(); exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (30, 50)).save(out, 'JPEG', exif=exif)
        path = self.root / 'exif.cbz'
        with zipfile.ZipFile(path, 'w') as archive: archive.writestr('1.jpg', out.getvalue())
        with staged_pages(inspect_book(path)) as records:
            self.assertEqual(records[0]['size'], (50, 30))
            with Image.open(records[0]['local_path']) as image:
                self.assertNotIn(image.getexif().get(274), range(2, 9))

    def test_preview_cap_checked_before_decode(self):
        book = inspect_book(self.book())
        with patch('local_import.PREVIEW_MEMORY_LIMIT', 100):
            with self.assertRaisesRegex(ValueError, '128 MiB'): preview_records(book)

    def test_pdf_inspection_unknown_metadata_and_encryption(self):
        path = self.root / 'filename.pdf'; path.write_bytes(b'fixture')
        with patch('local_import.poppler_tools', return_value=('info', 'raster')):
            with patch('local_import.run_tool', return_value='Title: Unknown\nPages: 3\nEncrypted: no\nAuthor: Writer'):
                book = inspect_book(path)
                self.assertEqual((book['title'], book['author'], book['pages']), ('filename', 'Writer', 3))
                self.assertEqual(book['series'], '')
            with patch('local_import.run_tool', return_value='Pages: 3\nEncrypted: yes (print:yes)'):
                with self.assertRaisesRegex(ValueError, 'Encrypted'): inspect_pdf(path)
            with patch('local_import.run_tool', return_value='Pages: 0'):
                with self.assertRaisesRegex(ValueError, 'no readable'): inspect_pdf(path)

    def test_pdf_raster_flags_bounded_preview_and_cleanup(self):
        path = self.root / 'input.pdf'; path.write_bytes(b'fixture')
        from local_import import file_identity
        book = dict(path=str(path), identity=file_identity(path), format='pdf', pages=40)
        arguments = []
        def raster(args, check):
            arguments.extend(args)
            prefix = Path(args[-1])
            for i in (1, 2): prefix.with_name(prefix.name + f'-{i:02}.jpg').write_bytes(png())
            return ''
        with patch('local_import.poppler_tools', return_value=('info', 'raster')), patch('local_import.run_tool', side_effect=raster):
            with staged_pages(book, page_limit=2) as records:
                directory = Path(records[0]['local_path']).parent
                self.assertEqual(len(records), 2)
                self.assertEqual(records[-1]['chapter_pages'], 40)
        self.assertFalse(directory.exists())
        self.assertEqual(arguments[1:10], ['-cropbox', '-r', '100', '-jpeg', '-jpegopt', 'quality=95,optimize=y', '-f', '1', '-l'])
        self.assertEqual(arguments[10], '2')
        def failure(args, check):
            arguments[:] = args
            Path(args[-1]).with_suffix('.jpg').write_bytes(b'partial raster')
            raise RuntimeError('raster failed')
        with patch('local_import.poppler_tools', return_value=('info', 'raster')), patch('local_import.run_tool', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'raster failed'):
                with staged_pages(book): pass
        self.assertEqual(arguments[10], '40')
        self.assertEqual(arguments[3], '300')
        self.assertFalse(Path(arguments[-1]).parent.exists())

    def test_preview_skips_oversized_pages_and_tries_beyond_sample_window(self):
        path = self.root / 'oversized.cbz'
        with zipfile.ZipFile(path, 'w') as archive:
            for i, size in enumerate(((100, 100), (100, 100), (10, 10), (100, 100), (10, 10)), 1):
                archive.writestr(f'{i}.png', png(size))
        book = inspect_book(path); messages = []
        with patch('local_import.PREVIEW_MEMORY_LIMIT', 1000):
            records = preview_records(book, limit=2, log=messages.append)
        self.assertEqual([r['page_in_chapter'] for r in records], [3, 5])
        self.assertTrue(all(r['chapter_pages'] == 5 for r in records))
        self.assertEqual(sum(r['size'][0]*r['size'][1]*4 for r in records), 800)
        self.assertEqual(len([m for m in messages if 'skipped oversized' in m]), 3)
        # Preview skips do not remove or relax validation of any final reading pages.
        with staged_pages(book) as final:
            self.assertEqual(len(final), 5)

    def test_preview_retains_safe_pages_when_combined_budget_is_full(self):
        path = self.root / 'budget.cbz'
        with zipfile.ZipFile(path, 'w') as archive:
            for i, size in enumerate(((10, 10), (15, 10), (10, 10)), 1):
                archive.writestr(f'{i}.png', png(size))
        messages = []
        with patch('local_import.PREVIEW_MEMORY_LIMIT', 900):
            records = preview_records(inspect_book(path), log=messages.append)
        self.assertEqual([r['page_in_chapter'] for r in records], [1, 3])
        self.assertTrue(any('page 2' in message and 'budget' in message for message in messages))

    def test_preview_all_unsafe_reports_sampling_error_and_logs_each_page(self):
        book = inspect_book(self.book()); messages = []
        with patch('local_import.PREVIEW_MEMORY_LIMIT', 100):
            with self.assertRaisesRegex(ValueError, '^No safe Live Preview samples'):
                preview_records(book, log=messages.append)
        self.assertEqual(len([m for m in messages if 'skipped oversized' in m]), book['pages'])

    def test_preview_cancellation_still_propagates(self):
        book = inspect_book(self.book())
        def cancel(): raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError): preview_records(book, check=cancel)

    def test_subprocess_cancel_terminates_and_reaps(self):
        started = time.monotonic()
        def cancel():
            if time.monotonic() - started > .2: raise InterruptedError()
        with self.assertRaises(InterruptedError):
            run_tool([sys.executable, '-c', 'import time; time.sleep(20)'], cancel)
        self.assertLess(time.monotonic()-started, 4)

    def test_pdf_validation_failure_preserves_existing_output(self):
        output = self.root / 'output.pdf'; output.write_bytes(b'previous')
        def write(path, *args): path.write_bytes(b'not a pdf'); return 2
        with patch('book_export._write_pdf', side_effect=write), patch('book_export.validate_pdf', side_effect=ValueError('invalid')):
            with self.assertRaisesRegex(ValueError, 'invalid'):
                write_book(output, 'pdf', iter(()))
        self.assertEqual(output.read_bytes(), b'previous')
        self.assertFalse(Path(str(output)+'.part').exists())

    def test_invalid_cover_indices_and_xml_entities_fallback(self):
        book = inspect_book(self.book(xml=b'<ComicInfo><Pages><Page Image="999" Type="FrontCover"/></Pages></ComicInfo>'))
        self.assertEqual(book['cover_index'], 0)
        root = ET.fromstring(comicinfo_for_import(book, {'title': 'Updated'}, 2))
        self.assertFalse(root.findall('Pages/Page'))
        from local_import import parse_comicinfo
        self.assertIsNone(parse_comicinfo(b'<!DOCTYPE ComicInfo [<!ENTITY t "x">]><ComicInfo>&t;</ComicInfo>'))

    def test_import_mode_state_clears_source_and_finalization(self):
        from workflow_state import HighPriestessState
        state = HighPriestessState(mode='volume')
        state.set_pending_query('retain')
        state.select_provider({'source_id': 'fixture', 'id': '1'})
        state.set_finalization_plan([{'title': 'old'}])
        self.assertTrue(state.change_mode('import'))
        self.assertIsNone(state.selected_provider_record)
        self.assertFalse(state.finalization_plan)
        self.assertEqual(state.pending_query_text, 'retain')
        self.assertTrue(state.change_mode('chapter'))

    def test_disk_and_blob_records_use_identical_renderer(self):
        from test_empress_pipeline import production_namespace
        from image_processing import ProcessingSettings
        ns = production_namespace()
        book = inspect_book(self.book())
        with staged_pages(book) as local:
            source = [dict(r, blob=Path(r['local_path']).read_bytes()) for r in local]
            for row in source: del row['local_path']
            for layout in ('original_pages', 'paired_landscape'):
                for settings in (ProcessingSettings(), ProcessingSettings(brightness=1.2, grayscale=True),
                                 ProcessingSettings(grayscale=True, output_depth=4, dithering='atkinson')):
                    source_jobs, _ = ns['output_page_jobs'](source, layout, 'rtl')
                    local_jobs, _ = ns['output_page_jobs'](local, layout, 'rtl')
                    self.assertEqual([ns['render_output_page'](j, settings) for j in source_jobs],
                                     [ns['render_output_page'](j, settings) for j in local_jobs])

    def test_packaged_modules_assets_and_no_pdf_binaries(self):
        from tools.build_plugin import files_to_package, syntax_check
        root = Path(__file__).resolve().parents[1]
        files = files_to_package(root)
        names = {name for path, name in files}
        self.assertTrue({'local_import.py', 'book_export.py', 'import_workflow.py', 'import_workers.py'} <= names)
        self.assertTrue(all(path.exists() for path, name in files))
        self.assertFalse(any(name.lower().endswith('.exe') for name in names))
        self.assertTrue({'assets/covers/background.png', 'assets/covers/stamp.png',
                         'assets/covers/anchor.png', 'assets/covers/BebasNeue-Regular.ttf'} <= names)
        syntax_check(root)


if __name__ == '__main__': unittest.main()
