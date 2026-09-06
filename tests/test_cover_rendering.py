"""PSD geometry, metadata identity, and real downloader cover/page isolation."""
import ast
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageChops, ImageOps

import cover_rendering as covers
from image_processing import ProcessingSettings
from tests.test_empress_pipeline import production_namespace, Source, Thread, Signal


def png(image):
    out = BytesIO(); image.save(out, 'PNG'); return out.getvalue()


def decoded(blob):
    with Image.open(BytesIO(blob)) as image:
        return image.convert('RGB')


class CoverRenderingTests(unittest.TestCase):
    def test_keep_is_byte_identical_even_without_decodable_art(self):
        for blob in (None, b'existing cover bytes'):
            self.assertIs(blob, covers.render_cover(blob))

    def test_volume_chapter_numbers_and_safe_fallbacks(self):
        cases = [({'volume':16}, '16'), ({'volume':8}, '08'),
                 ({'output_kind':'chapter','volume':16,'chapter_number':103}, '103'),
                 ({'output_kind':'chapter','chapter_number':'8.5'}, '08.5'),
                 ({'volume':0}, '00'), ({'volume':8,'zero_pad':False}, '8'),
                 ({'series_index':3}, '03'),
                 ({'output_kind':'chapter','series_index':9}, '09'),
                 ({'output_kind':'standalone','series_index':9}, '')]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs): self.assertEqual(expected,covers.badge_text(**kwargs))
        for value in (None, '', 'extra', 'NaN', 'Infinity', '-1', '1e99999', '1e-99999', True):
            self.assertEqual('',covers.badge_text(volume=value))
        self.assertEqual('Series',covers.cover_title('', 'Series'))
        self.assertEqual('Untitled Manga',covers.cover_title())

    def test_stamp_preserves_entire_main_area_without_tint(self):
        art=Image.new('RGB',(740,1200),(23,67,129))
        art.paste((223,192,11),(17,42,310,890))
        original=png(art)
        for kind,number in (('volume',8),('chapter',103)):
            result=decoded(covers.render_cover(original,mode='stamp',output_kind=kind,
                            volume=number,chapter_number=number))
            self.assertEqual((880,1200),result.size)
            self.assertIsNone(ImageChops.difference(art,result.crop((0,0,740,1200))).getbbox())
            strip=covers._art('stamp.png').convert('RGB')
            self.assertIsNone(ImageChops.difference(strip.crop((0,0,140,995)),result.crop((740,0,880,995))).getbbox())
        self.assertEqual(original,png(art))

    def test_stamp_fits_and_normalizes_exif_without_changing_source(self):
        image=Image.new('RGB',(300,180),(90,30,180)); image.paste('green',(0,0,80,180))
        exif=Image.Exif(); exif[274]=6
        buffer=BytesIO(); image.save(buffer,'JPEG',exif=exif)
        original=buffer.getvalue()
        with Image.open(BytesIO(original)) as image:
            expected=ImageOps.fit(ImageOps.exif_transpose(image).convert('RGB'),(740,1200),method=covers.LANCZOS)
        result=decoded(covers.render_cover(original,mode='stamp'))
        self.assertIsNone(ImageChops.difference(expected,result.crop((0,0,740,1200))).getbbox())

    def test_generate_uses_psd_layers_and_ignores_original_art(self):
        for kind,number in (('volume',16),('chapter',103)):
            args=dict(mode='generate',title='Chainsaw Man (Official Colored)',
                      output_kind=kind,volume=number,chapter_number=number)
            blob=covers.render_cover(None,**args)
            self.assertEqual(blob,covers.render_cover(b'invalid source',**args))
            result=decoded(blob); self.assertEqual((880,1200),result.size)
            expected=Image.new('RGBA',covers.CANVAS_SIZE,covers.PALETTE['midnight_blue'])
            expected.alpha_composite(covers._art('background.png'))
            background=expected.copy()
            expected.alpha_composite(covers._art('anchor.png'),covers.ANCHOR_POSITION)
            region=(0,437,740,1200)
            self.assertIsNone(ImageChops.difference(expected.convert('RGB').crop(region),result.crop(region)).getbbox())
            self.assertIsNotNone(ImageChops.difference(background.convert('RGB').crop(region),result.crop(region)).getbbox())
            self.assertLessEqual(covers._art('anchor.png').getchannel('A').getextrema()[1],156)

    def test_badge_changes_only_number_region_for_both_modes(self):
        for mode in ('stamp','generate'):
            source=png(Image.new('RGB',(740,1200),'blue'))
            a=decoded(covers.render_cover(source,mode=mode,volume=8))
            b=decoded(covers.render_cover(source,mode=mode,output_kind='chapter',chapter_number=103))
            box=ImageChops.difference(a,b).getbbox()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box[0],760); self.assertLessEqual(box[2],862)
            self.assertGreaterEqual(box[1],1024); self.assertLessEqual(box[3],1112)

    def test_long_and_missing_titles_stay_in_title_box(self):
        for title in ('', 'A long title ' * 50, 'UnbrokenTitle' * 60,
                      'Chainsaw Man (Official Colored)'):
            text,font,spacing,box=covers.title_layout(covers.cover_title(title))
            self.assertTrue(text); self.assertGreaterEqual(font.size,38)
            self.assertLessEqual(box[2]-box[0],600)
            self.assertLessEqual(box[3]-box[1],245)
            result=decoded(covers.render_cover(mode='generate',title=title))
            self.assertEqual((880,1200),result.size)

    def test_missing_art_omits_stamp_and_generate_needs_no_art(self):
        self.assertIsNone(covers.render_cover(mode='stamp'))
        self.assertEqual((880,1200),decoded(covers.render_cover(mode='generate')).size)

    def test_zip_resource_loader_is_used_without_local_paths(self):
        names=('background.png','anchor.png','stamp.png','BebasNeue-Regular.ttf')
        resources={'assets/covers/'+name:covers._resource(name) for name in names}
        covers._resource.cache_clear()
        try:
            with patch.object(covers,'get_resources',resources.get,create=True):
                self.assertEqual((880,1200),decoded(covers.render_cover(mode='generate')).size)
        finally:
            covers._resource.cache_clear()


class CoverWorkerTests(unittest.TestCase):
    def setUp(self):
        self.ns=production_namespace()

    def test_real_downloader_modes_leave_portrait_and_landscape_cbz_identical(self):
        for layout in ('original_pages','paired_landscape'):
            for kind,number in (('volume',8),('chapter',103),('standalone',None)):
                archives=[]
                for mode in ('keep','stamp','generate'):
                    with self.subTest(layout=layout,kind=kind,mode=mode):
                        source=Source()
                        worker=self.ns['DownloadWorker'](source,'url','Title','Author','Series','en',1,1,
                            True,True,(),cover_mode=mode,page_layout=layout,
                            processing=ProcessingSettings(brightness=1.5,grayscale=True))
                        state=dict(bytes=0,pages_done=0,pages_total=3,volume_done=0,started=time.time())
                        volume=number if kind == 'volume' else None
                        chapter=number if kind == 'chapter' else None
                        with tempfile.TemporaryDirectory() as directory:
                            output=Path(directory)/'test.cbz'
                            cover=worker._download_group([dict(id='one',chapter=str(number),pages=3)],
                                output,'Title',volume,'cover.png',state,1,1,3,chapter_number=chapter)
                            actual=Path(cover).read_bytes()
                            expected=covers.render_cover(source.blob if mode != 'generate' else None,
                                mode=mode,title='Title',series='Series',output_kind=kind,
                                volume=volume,chapter_number=chapter)
                            self.assertEqual(expected,actual)
                            with zipfile.ZipFile(output) as archive:
                                archives.append({n:archive.read(n) for n in archive.namelist()})
                                self.assertFalse(any('cover' in n.lower() for n in archive.namelist()))
                        self.assertEqual(3 if mode == 'generate' else 4,source.fetches)
                self.assertEqual(archives[0],archives[1]); self.assertEqual(archives[0],archives[2])

    def test_explicit_modes_override_source_cover_checkbox(self):
        for mode,fetch_art in (('keep',False),('stamp',True),('generate',False)):
            worker=self.ns['DownloadWorker'](Source(),'url','T','A','S','en',1,1,False,True,(),cover_mode=mode)
            self.assertEqual(fetch_art,worker.covers)

    def preview_worker(self, mode):
        ns=dict(self.ns,ImageOps=ImageOps)
        node=next(n for n in ast.parse(Path('main.py').read_text(encoding='utf-8')).body
                  if isinstance(n,ast.ClassDef) and n.name=='CoverPreviewWorker')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'main.py','exec'),ns)
        source=Source()
        return source,ns['CoverPreviewWorker'](source,'cover.png',dict(mode=mode,title='Title',volume=16))

    def test_preview_runs_same_compositor_and_generate_skips_network(self):
        for mode in ('stamp','generate'):
            source,worker=self.preview_worker(mode); worker.run()
            self.assertFalse(worker.failed.calls)
            result=decoded(worker.ready.calls[0][0])
            expected=decoded(covers.render_cover(source.blob,mode=mode,title='Title',volume=16))
            expected.thumbnail((220,300),covers.LANCZOS)
            self.assertIsNone(ImageChops.difference(expected,result).getbbox())
            self.assertEqual(0 if mode=='generate' else 1,source.fetches)

    def test_preview_cancel_before_and_during_fetch_suppresses_result(self):
        source,worker=self.preview_worker('stamp')
        worker.requestInterruption(); worker.run()
        self.assertEqual(0,source.fetches); self.assertFalse(worker.ready.calls)
        source,worker=self.preview_worker('stamp')
        def fetch(*args,**kwargs): worker.requestInterruption(); return source.blob
        source.fetch_binary=fetch; worker.run()
        self.assertFalse(worker.ready.calls); self.assertFalse(worker.failed.calls)


if __name__ == '__main__': unittest.main()
