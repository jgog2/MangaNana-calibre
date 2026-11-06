"""Patch 1F edition evidence must stay scoped to the selected provider record."""
import ast
from pathlib import Path
import unittest

from calibre_plugins.manganana.discovery.canonical_identity import edition_display_label, edition_identity


def load_helper():
    tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8'))
    node=next(
        item for item in tree.body
        if isinstance(item,ast.FunctionDef) and item.name == '_selected_provider_edition_evidence'
    )
    namespace={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'app/main.py','exec'),namespace)
    return namespace['_selected_provider_edition_evidence']


edition_evidence=load_helper()


class EditionEvidenceIsolationTests(unittest.TestCase):
    def classify(self, provider, metadata):
        evidence=edition_evidence(provider,metadata)
        return edition_identity(evidence),edition_display_label(evidence),evidence

    def test_standard_primary_ignores_official_colored_alias(self):
        identity,badge,evidence=self.classify(
            {
                'title':'Chainsaw Man',
                'full_title':'Chainsaw Man',
                '_provider_native_title':'Chainsaw Man',
                'alternate_titles':['Chainsaw Man (Official Colored)'],
            },
            {
                'title':'Chainsaw Man',
                'titles':[
                    {'title':'Chainsaw Man','primary':True},
                    {'title':'Chainsaw Man (Official Colored)','primary':False},
                ],
            },
        )
        self.assertEqual('original',identity)
        self.assertEqual('',badge)
        self.assertEqual('Chainsaw Man',evidence['full_title'])

    def test_real_colored_primary_remains_official_color(self):
        identity,badge,_=self.classify(
            {
                'title':'Chainsaw Man - Digital Colored Comics',
                'full_title':'Chainsaw Man - Digital Colored Comics',
                '_provider_native_title':'Chainsaw Man - Digital Colored Comics',
            },
            {'title':'Chainsaw Man - Digital Colored Comics'},
        )
        self.assertEqual('official_color',identity)
        self.assertEqual('COLOR',badge)

    def test_standard_primary_ignores_fan_colored_alias(self):
        identity,badge,_=self.classify(
            {
                'title':'One Punch Man',
                'full_title':'One Punch Man',
                '_provider_native_title':'One Punch Man',
                'alternate_titles':['One Punch Man (Fan Colored)'],
            },
            {
                'title':'One Punch Man',
                'titles':[
                    {'title':'One Punch Man','primary':True},
                    {'title':'One Punch Man (Fan Colored)','primary':False},
                ],
            },
        )
        self.assertEqual('original',identity)
        self.assertEqual('',badge)

    def test_real_fan_colored_primary_remains_fan_color(self):
        identity,badge,_=self.classify(
            {
                'title':'One Punch Man (Fan Colored)',
                'full_title':'One Punch Man (Fan Colored)',
                '_provider_native_title':'One Punch Man (Fan Colored)',
            },
            {'title':'One Punch Man (Fan Colored)'},
        )
        self.assertEqual('fan_color',identity)
        self.assertEqual('FAN COLOR',badge)

    def test_explicit_provider_edition_fields_are_preserved(self):
        evidence=edition_evidence(
            {'title':'Series','edition':'official_color','badge':'COLOR','is_colored':True},
            {'title':'Series'},
        )
        self.assertEqual('official_color',edition_identity(evidence))
        self.assertEqual('COLOR',edition_display_label(evidence))
        self.assertTrue(evidence['is_colored'])

    def test_direct_load_uses_metadata_primary_only(self):
        evidence=edition_evidence(
            {'title':'Wrong sibling','edition':'official_color'},
            {'title':'Chainsaw Man'},
            direct=True,
        )
        self.assertEqual({'title':'Chainsaw Man','full_title':'Chainsaw Man'},evidence)
        self.assertEqual('original',edition_identity(evidence))

    def test_apply_loaded_manga_uses_isolated_helper(self):
        tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8'))
        dialog=next(item for item in tree.body if isinstance(item,ast.ClassDef) and item.name == 'MangaNanaDialog')
        method=next(item for item in dialog.body if isinstance(item,ast.FunctionDef) and item.name == '_apply_loaded_manga')
        source=ast.unparse(method)
        self.assertIn('_selected_provider_edition_evidence',source)
        self.assertNotIn("' '.join(x.get('title', '') for x in md.get('titles', []))",source)


if __name__ == '__main__':
    unittest.main()
