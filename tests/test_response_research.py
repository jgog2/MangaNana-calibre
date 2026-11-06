"""Cover presentation reuse without output metadata or mutable raster sharing."""
import unittest
import ast
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image,ImageOps
from calibre_plugins.manganana.books.imaging import cover_rendering as covers
from calibre_plugins.manganana.books.output.finalization_covers import FinalizationCoverMixin

class ResponseResearchTests(unittest.TestCase):
    def test_late_fallback_terminal_acquisition_releases_reference_wait(self):
        path=Path(__file__).resolve().parents[1]/'app/main.py'
        tree=ast.parse(path.read_text(encoding='utf8'))
        fn=next(n for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)and n.name=='_apply_chapter_plan')
        scope={'chapter_sort_key':lambda row:row['id']}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),scope)
        d=SimpleNamespace(_volume_plan_request_id=7,language=SimpleNamespace(currentData=lambda:'en'),
            _pending_cross_source_plan=None,_selected_fallback_worker=None,_workflow_inventory_generation=11,
            _reference_waiting_for_inventory=True,_start_reference_lookup=Mock(),_try_finalize_chapter_projection=Mock(),
            workflow_state=SimpleNamespace(settle_chapter_acquisition=Mock(return_value=True)))
        scope['_apply_chapter_plan'](d,7,'en',[{'id':'exact'}])
        d._start_reference_lookup.assert_called_once();d._try_finalize_chapter_projection.assert_called_once()
        d._reference_waiting_for_inventory=False;d._start_reference_lookup.reset_mock()
        scope['_apply_chapter_plan'](d,7,'en',[{'id':'exact'}])
        d._start_reference_lookup.assert_not_called()

    def test_direct_preview_has_the_full_cover_pixels_and_independent_storage(self):
        for mode in ('generate','stamp','keep'):
            out=BytesIO();Image.new('RGB',(120,190),'teal').save(out,'PNG');raw=out.getvalue()
            options=dict(mode=mode,title='Controlled title',volume=12)
            full=covers.render_cover(raw,**options)
            direct=covers.render_cover_image(raw,**options)
            with Image.open(BytesIO(full))as image:
                expected=ImageOps.exif_transpose(image).convert('RGB')
            self.assertEqual(expected.tobytes(),direct.tobytes())
            direct.paste('red',(0,0,60,60))
            self.assertEqual(expected.tobytes(),covers.render_cover_image(raw,**options).tobytes())

    def test_title_cache_is_bounded_and_holds_immutable_cropped_pixels(self):
        covers._title_raster.cache_clear()
        for n in range(6):covers._title_raster('Cache title '+str(n))
        self.assertEqual(4,covers._title_raster.cache_info().currsize)
        size,pixels=covers._title_raster('Cache title 5')
        self.assertIsInstance(pixels,bytes)
        self.assertEqual(size[0]*size[1]*4,len(pixels))
        covers._title_raster.cache_clear()

    def test_cover_schedule_retains_valid_row_and_inflight_worker_until_key_comparison(self):
        row={'cover_thumbnail':b'valid','cover_key':('keep','identity'),'cover_state':'ready'}
        worker=Mock();timer=Mock()
        d=SimpleNamespace(preview_data={'rows':[row]},_cover_worker=worker,_cover_update_timer=timer,
                          _cancel_output_covers=Mock())
        FinalizationCoverMixin._schedule_output_covers(d)
        self.assertEqual(b'valid',row['cover_thumbnail']);self.assertEqual('ready',row['cover_state'])
        worker.requestInterruption.assert_not_called();d._cancel_output_covers.assert_not_called();timer.start.assert_called_once()
