"""Pure preset persistence and production atomic UI-state contracts."""
from copy import deepcopy
import unittest

from image_processing import ProcessingSettings
from processing_presets import (
    BUILTIN_PRESETS, BUILTIN_PRESETS_BY_ID, ProcessingPreset, delete_user_preset,
    load_user_presets, matching_preset, normalized_settings_snapshot,
    save_user_preset, settings_from_payload, settings_to_payload,
    user_presets_payload, validate_user_preset_name,
)
from tests import test_empress_pipeline as pipeline


class ProcessingPresetTests(unittest.TestCase):
    def test_five_stable_valid_builtins_and_values(self):
        self.assertEqual(('original','bw_manga','high_contrast_manga','soft_grayscale','color_enhancement'),
                         tuple(p.preset_id for p in BUILTIN_PRESETS))
        self.assertTrue(all(isinstance(p.settings,ProcessingSettings) and p.builtin for p in BUILTIN_PRESETS))
        expected=(
            ProcessingSettings(),
            ProcessingSettings(contrast=1.15,sharpness=1.10,grayscale=True),
            ProcessingSettings(contrast=1.30,gamma=.95,sharpness=1.20,grayscale=True),
            ProcessingSettings(contrast=.95,gamma=1.05,grayscale=True),
            ProcessingSettings(contrast=1.08,saturation=1.25,sharpness=1.10),
        )
        self.assertEqual(expected,tuple(p.settings for p in BUILTIN_PRESETS))
        self.assertEqual(ProcessingSettings(),BUILTIN_PRESETS_BY_ID['original'].settings)
        high=BUILTIN_PRESETS_BY_ID['high_contrast_manga']
        self.assertEqual('High Contrast B&W',high.name)
        self.assertEqual('high_contrast_manga',matching_preset(high.settings).preset_id)
        self.assertEqual(1.25,BUILTIN_PRESETS_BY_ID['color_enhancement'].settings.saturation)

    def test_schema_v1_round_trip_is_complete_and_strict(self):
        for settings in (ProcessingSettings(),ProcessingSettings(
                brightness=.25,contrast=2,gamma=2.5,saturation=3,sharpness=0,
                grayscale=True,output_depth=2,dithering='sierra-lite',dither_strength=2)):
            payload=settings_to_payload(settings)
            self.assertEqual(1,payload['version']); self.assertEqual(settings,settings_from_payload(payload))
            self.assertIs(settings,normalized_settings_snapshot(settings))
        with self.assertRaises(TypeError): normalized_settings_snapshot({})

    def test_malformed_presets_fail_independently(self):
        good=settings_to_payload(ProcessingSettings(contrast=1.2))
        malformed=(None,[],{}, {'version':2},dict(good,unknown=True),
                   dict(good,grayscale='yes'),dict(good,gamma='bad'),dict(good,output_depth=99))
        for value in malformed:
            with self.subTest(value=value):
                self.assertEqual((),load_user_presets({'Bad':value}))
        loaded=load_user_presets({'Bad':{'version':2},'Good':good})
        self.assertEqual(('Good',),tuple(p.name for p in loaded))

    def test_reserved_and_duplicate_names(self):
        for name in ('','  ','Custom',' custom ','Original','b&w MANGA'):
            with self.assertRaises(ValueError): validate_user_preset_name(name)
        self.assertEqual('My Manga Preset',validate_user_preset_name(' My   Manga Preset '))
        with self.assertRaises(ValueError): validate_user_preset_name('test',('Test',))

    def test_user_save_load_update_rename_delete_and_builtin_protection(self):
        settings=ProcessingSettings(grayscale=True,output_depth=4,dithering='atkinson',dither_strength=1.5)
        presets=save_user_preset((),' Gray Four ',settings)
        stored=user_presets_payload(presets); reloaded=load_user_presets(deepcopy(stored))
        self.assertEqual(presets,reloaded); self.assertEqual(settings,reloaded[0].settings)
        changed=ProcessingSettings(brightness=1.5,output_depth=8,dithering='floyd-steinberg',dither_strength=.5)
        presets=save_user_preset(reloaded,'Gray Four',changed,current_name='Gray Four')
        self.assertEqual(changed,presets[0].settings)
        presets=save_user_preset(presets,' Color Eight ',changed,current_name='Gray Four')
        self.assertEqual('Color Eight',presets[0].name)
        self.assertEqual((),delete_user_preset(presets,'Color Eight'))
        for operation in (
            lambda:save_user_preset((),'Original',settings),
            lambda:save_user_preset((),'Renamed',settings,current_name='Original'),
            lambda:delete_user_preset((),'Original')):
            with self.assertRaises(ValueError): operation()

    def test_exact_matching_prefers_builtin_then_user_and_custom_is_unsaved(self):
        user=save_user_preset((),'Experiment',ProcessingSettings(contrast=1.2))
        self.assertEqual('original',matching_preset(ProcessingSettings(),user).preset_id)
        self.assertEqual('Experiment',matching_preset(ProcessingSettings(contrast=1.2),user).name)
        self.assertIsNone(matching_preset(ProcessingSettings(contrast=1.25),user))
        self.assertNotIn('Custom',user_presets_payload(user))

    def test_active_preset_is_not_part_of_persisted_payload(self):
        presets=save_user_preset((),'Saved Test',ProcessingSettings(sharpness=2))
        payload=user_presets_payload(presets)
        self.assertEqual(('Saved Test',),tuple(payload))
        self.assertNotIn('active_preset',repr(payload).casefold())


class PresetUiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): pipeline.PipelineTests.setUpClass()
    @classmethod
    def tearDownClass(cls): pipeline.PipelineTests.tearDownClass()
    def setUp(self): self.fixture=pipeline.PipelineTests(); self.fixture.setUp()

    def test_builtin_application_and_reset_are_atomic(self):
        source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        c._apply_processing_preset(BUILTIN_PRESETS_BY_ID['high_contrast_manga'])
        self.assertEqual(BUILTIN_PRESETS_BY_ID['high_contrast_manga'].settings,c.processing)
        self.assertEqual(1,c.transitions); self.assertTrue(c._processing_pending)
        self.assertFalse(c._processing_controls['saturation'][0].enabled)
        c._reset_processing()
        self.assertEqual(ProcessingSettings(),c.processing)
        self.assertEqual(2,c.transitions)
        c._flush_processing_render(); self.assertEqual(1,len(c.started))
        c._processing_worker.run(); self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_grayscale_and_color_reduced_depth_dithering_restore_every_field(self):
        c=self.fixture.controls()
        for settings in (ProcessingSettings(grayscale=True,output_depth=2,dithering='atkinson',dither_strength=2),
                         ProcessingSettings(brightness=1.5,output_depth=8,dithering='sierra-lite',dither_strength=.5)):
            preset=ProcessingPreset('test','Test',settings,False)
            before=c.transitions; c._apply_processing_preset(preset)
            self.assertEqual(settings,c.processing); self.assertEqual(before+1,c.transitions)
            self.assertEqual(settings.output_depth,c.output_depth.currentData())
            self.assertEqual(settings.dithering,c.dithering.currentData())
            self.assertEqual(round(settings.dither_strength*100),c.dither_strength.value())

    def test_manual_change_custom_and_exact_rematch_logic(self):
        c=self.fixture.controls()
        # Pure matching is exactly what the production selector synchronizes to.
        c._apply_processing_preset(BUILTIN_PRESETS_BY_ID['bw_manga'])
        self.assertEqual('bw_manga',matching_preset(c.processing).preset_id)
        c._processing_controls['contrast'][0].setValue(120); c._processing_changed()
        self.assertIsNone(matching_preset(c.processing))
        c._processing_controls['contrast'][0].setValue(115); c._processing_changed()
        self.assertEqual('bw_manga',matching_preset(c.processing).preset_id)

    def test_rapid_presets_only_newest_render_can_win(self):
        _source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        c._schedule_processing_render(immediate=True); first=c._processing_worker
        for preset_id in ('bw_manga','high_contrast_manga','color_enhancement'):
            c._apply_processing_preset(BUILTIN_PRESETS_BY_ID[preset_id])
            c._flush_processing_render()
        self.assertEqual(1,len(c.started)); self.assertTrue(first.interrupted)
        first.finished.emit(); self.assertEqual(2,len(c.started))
        c._processing_worker.run()
        self.assertEqual(BUILTIN_PRESETS_BY_ID['color_enhancement'].settings,
                         c.displayed[-1]['processing'])


if __name__=='__main__': unittest.main()
