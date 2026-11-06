"""Presentation evidence controls; run in Calibre's validated Qt environment."""
import hashlib
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
if 'calibre_plugins.manganana' not in sys.modules:
    package=types.ModuleType('calibre_plugins.manganana')
    package.__path__=[str(ROOT)]
    sys.modules['calibre_plugins.manganana']=package
from calibre_plugins.manganana.presentation.choose_manga_ui import membership_summary
from calibre_plugins.manganana.presentation.choose_manga_background import desktop_fragment, HEADER, SHADER, PROVIDER_PRESETS, PALETTE, DEFAULTS, NO_SELECTION_SHADER


class PresentationEvidenceTests(unittest.TestCase):
    def summary(self, rows):
        return membership_summary({'chapters':rows})

    def test_contiguous_explicit_members(self):
        self.assertEqual(self.summary([{'chapter':str(n)} for n in (3,1,2)]),('3 chapter entries','Chapters: 3, 1, 2'))

    def test_gaps_are_not_extrapolated(self):
        self.assertEqual(self.summary([{'chapter':'1'},{'chapter':'3'}]),('2 chapter entries','Chapters: 1, 3'))

    def test_fractional_members_keep_identity(self):
        self.assertEqual(self.summary([{'chapter':'2'},{'chapter':'2.1'}]),('2 chapter entries','Chapters: 2, 2.1'))

    def test_duplicates_are_not_compressed_into_range(self):
        self.assertEqual(self.summary([{'chapter':'1'},{'chapter':'1'}])[0],'2 chapter entries')

    def test_zero_is_not_treated_as_missing(self):
        self.assertEqual(self.summary([{'chapter':0}]),('1 chapter entry','Chapters: 0'))

    def test_opaque_numeric_ids_are_never_chapter_numbers(self):
        self.assertEqual(self.summary([{'id':'41'},{'id':'42'}]),('2 chapter entries','Chapters: ID: 41, ID: 42'))

    def test_empty_or_aggregate_only_membership_remains_unknown(self):
        self.assertEqual(membership_summary({'chapter_count':12}),('Entry count unavailable',''))
        self.assertEqual(membership_summary(None),('Entry count unavailable',''))

    def test_explicit_number_field_supported(self):
        self.assertEqual(self.summary([{'number':6},{'number':7}])[0],'2 chapter entries')

    def test_source_shader_is_exact_owner_file(self):
        self.assertEqual(hashlib.sha256(SHADER.read_bytes()).hexdigest(),'e378ee9dc10104f5d25fd0e6959e50f2e1855be569ed1e7001582213bb86c17d')

    def test_desktop_adaptation_changes_only_precision_and_output_binding(self):
        source=SHADER.read_text(encoding='utf-8')
        self.assertEqual(desktop_fragment(source),HEADER+source.replace('precision highp float;',''))
        self.assertIn('SPDX-FileCopyrightText: 2026 E. T. Carter',desktop_fragment(source))

    def test_exact_palette_and_defaults(self):
        self.assertEqual(PALETTE,((.231,.510,.965),(.659,.333,.969),(.133,.827,.933),(.957,.247,.369)))
        self.assertEqual(DEFAULTS,dict(u_driftSpeed=.30,u_softness=.85,u_warp=.95,u_heat=.7,u_mouseInfluence=0.))

    def test_explicit_provider_files(self):
        self.assertEqual({key:value.name for key,value in PROVIDER_PRESETS.items()}, {
            'mangadex':'MangaDex_Shader.frag','mangapill':'MangaPill_Shader.frag',
            'weebcentral':'WeebCentral_Shader.frag','mangak':'MangaK_Shader.frag','atsu':'Atsu_Shader.frag'})

    def test_shadertoy_wrapper_and_uniforms(self):
        result=desktop_fragment('void mainImage(out vec4 c, in vec2 p) { c=vec4(p/iResolution.xy,iTime,1.); }')
        self.assertIn('uniform vec3 iResolution;',result)
        self.assertIn('uniform float iTime;',result)
        self.assertIn('mainImage(shaderColor, gl_FragCoord.xy)',result)

    def test_conventional_main_is_not_wrapped_again(self):
        result=desktop_fragment('#version 330 core\nuniform float iTime;\nvoid main(){gl_FragColor=vec4(iTime);}')
        self.assertEqual(result.count('void main('),1)
        self.assertEqual(result.count('uniform float iTime;'),1)
        self.assertEqual(result.count('#version'),1)

    def test_comments_do_not_define_entry_points(self):
        result=desktop_fragment('// do not add main()\nvoid mainImage(out vec4 c, in vec2 p){c=vec4(1.);}')
        self.assertIn('void main() { mainImage',result)
        with self.assertRaises(ValueError):
            desktop_fragment('// void main() {}')

    def test_all_provider_shader_notices_preserved(self):
        for path in PROVIDER_PRESETS.values():
            text=path.read_text(encoding='utf-8')
            self.assertIn('SPDX-License-Identifier: MIT',text)
            self.assertIn('SPDX-FileCopyrightText: 2026 E. T. Carter',text)

    def test_oil_is_not_a_provider(self):
        self.assertEqual(len(PROVIDER_PRESETS),5)
        self.assertNotIn(NO_SELECTION_SHADER,PROVIDER_PRESETS.values())
        self.assertEqual(NO_SELECTION_SHADER.name,'NoSelection_Shader.frag')

    def test_oil_source_and_license_preserved(self):
        original=Path('C:/MangaNana-Dev/MangaNana-calibre/assets/hero_shaders/NoSelection_Shader.frag')
        self.assertEqual(NO_SELECTION_SHADER.read_bytes(),original.read_bytes())
        self.assertIn('SPDX-License-Identifier: MIT',NO_SELECTION_SHADER.read_text(encoding='utf-8'))
        self.assertIn('E. T. Carter',NO_SELECTION_SHADER.with_name('LICENSE.NoSelection.txt').read_text(encoding='utf-8'))

    def test_oil_compatibility_preserves_shader_body(self):
        source=NO_SELECTION_SHADER.read_text(encoding='utf-8')
        adapted=desktop_fragment(source)
        self.assertIn(source,adapted)
        self.assertIn('uniform float iTime;',adapted)
        self.assertIn('uniform vec3 iResolution;',adapted)
        self.assertEqual(adapted.count('void main()'),1)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromTestCase(PresentationEvidenceTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
