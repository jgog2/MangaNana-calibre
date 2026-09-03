"""Execute the actual metadata language/reference statements without Qt or sleeps."""
import ast
from pathlib import Path
import unittest

from google_books_reference import GoogleBooksArtworkResolver


MAIN = (Path(__file__).resolve().parent.parent / 'main.py').read_text(encoding='utf-8')
TREE = ast.parse(MAIN)


class Combo:
    def __init__(self): self.items=[]; self.index=-1
    def blockSignals(self, _blocked): pass
    def clear(self): self.items=[]; self.index=-1
    def addItem(self, label, value): self.items.append((label,value))
    def findData(self, value):
        return next((i for i,row in enumerate(self.items) if row[1]==value),-1)
    def setCurrentIndex(self, index): self.index=index
    def setEnabled(self, _enabled): pass
    def currentData(self): return self.items[self.index][1] if self.index>=0 else None


def execute_language_flow(available, requested='', preference='en'):
    populate=next(node for node in TREE.body if isinstance(node,ast.FunctionDef)
                  and node.name=='populate_download_languages')
    apply=next(node for node in ast.walk(TREE) if isinstance(node,ast.FunctionDef)
               and node.name=='_apply_loaded_manga')
    statements=[]
    for node in apply.body:
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name)
                and target.id=='available' for target in node.targets):
            statements.append(node)
        elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
            func=node.value.func
            if ((isinstance(func,ast.Name) and func.id=='populate_download_languages') or
                    (isinstance(func,ast.Attribute) and func.attr in
                     ('_seed_publication_manifest','_start_reference_lookup'))):
                statements.append(node)
    class Dialog:
        def __init__(self): self.language=Combo(); self.evidence=[]
        def _seed_publication_manifest(self,*_args): pass
        def _start_reference_lookup(self):
            self.evidence.append({'requested_language':self.language.currentData() or ''})
    dialog=Dialog()
    namespace={'self':dialog,'md':{'available_languages':available},
               'requested_language':requested,'prefs':{'language':preference},
               'provider_description':'','pending':{},
               'MAJOR_MANGA_LANGUAGES':(('English','en'),('Spanish','es')),
               'language_label':lambda code:code}
    exec(compile(ast.Module(body=[populate],type_ignores=[]),'main.py','exec'),namespace)
    exec(compile(ast.Module(body=statements,type_ignores=[]),'main.py','exec'),namespace)
    return dialog


class ReferenceLanguageOrderTests(unittest.TestCase):
    def test_stale_metadata_cannot_change_new_selection_or_language(self):
        method=next(node for node in ast.walk(TREE) if isinstance(node,ast.FunctionDef)
                    and node.name=='_apply_loaded_manga')
        namespace={}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'main.py','exec'),namespace)
        class CurrentSelection:
            _manga_request_id=2
            loaded_metadata={'title':'new title'}
            language=Combo()
        current=CurrentSelection()
        current.language.addItem('Spanish','es'); current.language.setCurrentIndex(0)
        namespace['_apply_loaded_manga'](current,1,{'metadata':{
            'title':'old title','available_languages':['en'],
        }})
        self.assertEqual('new title',current.loaded_metadata['title'])
        self.assertEqual('es',current.language.currentData())

    def test_empty_selector_is_populated_before_english_reference_snapshot(self):
        dialog=execute_language_flow(['en'])
        self.assertEqual('en',dialog.language.currentData())
        self.assertEqual([{'requested_language':'en'}],dialog.evidence)

    def test_reference_receives_actual_spanish_fallback_not_english_preference(self):
        dialog=execute_language_flow(['es'])
        self.assertEqual('es',dialog.language.currentData())
        self.assertEqual([{'requested_language':'es'}],dialog.evidence)

    def test_explicit_english_selection_with_multiple_provider_languages(self):
        dialog=execute_language_flow(['en','es'],requested='en',preference='es')
        self.assertEqual([{'requested_language':'en'}],dialog.evidence)

    def test_actual_reference_method_snapshots_language_before_worker_construction(self):
        method=next(node for node in ast.walk(TREE) if isinstance(node,ast.FunctionDef)
                    and node.name=='_start_reference_lookup')
        source=ast.get_source_segment(MAIN,method)
        self.assertLess(source.index("evidence['requested_language']"),
                        source.index('ReferenceLookupWorker('))
        self.assertIn("self.language.currentData() or ''",source)

    def test_google_context_uses_populated_language_without_assuming_english(self):
        for languages,eligible in ((['en'],True),(['es'],False)):
            with self.subTest(languages=languages):
                dialog=execute_language_flow(languages)
                resolver=GoogleBooksArtworkResolver(api_key='fake-key',enabled=True,
                    request_json=lambda _params:{'items':[]})
                result=resolver.resolve({**dialog.evidence[0],'edition_profile':'standard',
                    'canonical_title':'Work','canonical_creators':('Creator',)},('1',))
                self.assertEqual(eligible,result['status'] not in
                                 ('disabled','unavailable_publication_context'))
