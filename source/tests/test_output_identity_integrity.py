"""Identity/override regressions independent of Qt and display numbering."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('integrity_test_package');package.__path__=[str(ROOT)]
sys.modules[package.__name__]=package
spec=importlib.util.spec_from_file_location(package.__name__+'.output_series_metadata',ROOT/'books/output/output_series_metadata.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def bound(chapters,kind='chapter',**kw):
    row=dict(kind=kind,chapter=chapters[0] if kind=='chapter' else None,
             group={'chapters':chapters},volume=kw.pop('volume',None),title='Before')
    return m.bind_output_identity(row,source_id=kw.pop('source_id','weebcentral'),series_ref=kw.pop('series_ref','exact-series'),**kw)

class OutputIdentityIntegrityTests(unittest.TestCase):
    def test_real_berserk_namespaces_and_prologues_never_share_keys(self):
        for sid,labels in (('weebcentral',('Prologue 1','Prologue 2')),('mangapill',('1','1'))):
            records=json.loads((ROOT/'build/madb-bridge-integration/native-on-repaired'/sid/'cold-acquisition.json').read_text())
            selected=[r for r in records if r['chapter'] in labels][:2]
            self.assertEqual(len(selected),2)
            rows=[bound([r],source_id=sid) for r in selected]
            self.assertNotEqual(m.output_identity(rows[0]),m.output_identity(rows[1]))
            edits={m.output_identity(rows[0]):{'title':'First','series_index':67.5},
                   m.output_identity(rows[1]):{'title':'Second','series_index':23}}
            for row,title,index in zip(reversed(rows),('Second','First'),(23,67.5)):
                row['output_overrides']=edits[m.output_identity(row)]
                flat=dict(row,**m.effective_output_metadata(row))
                self.assertEqual((flat['title'],flat['series_index']),(title,index))
                self.assertEqual(m.output_identity(flat),m.output_identity(row))

    def test_key_survives_reconstruction_order_bibliography_and_format(self):
        records=[{'id':'a','chapter':'1'},{'id':'b','chapter':'1'}]
        original=bound(records,'volume',volume=5)
        reconstructed=bound(list(reversed(copy.deepcopy(records))),'volume',volume=5)
        reconstructed.update(title='Changed',series='Edited',series_index_override=123,format='pdf')
        self.assertEqual(m.output_identity(original),m.output_identity(reconstructed))
        self.assertNotEqual(m.output_identity(original),m.output_identity(bound(records[:1])))
        self.assertNotEqual(m.output_identity(original),m.output_identity(bound(records,'volume',volume=5,edition='color')))
        self.assertNotEqual(m.output_identity(original),m.output_identity(bound(records,'volume',volume=5,source_id='mangapill')))
        self.assertNotEqual(m.output_identity(original),m.output_identity(bound(records,'volume',volume=5,series_ref='other-series')))

    def test_nonnumeric_labels_keep_identity_and_safe_numeric_policy(self):
        for label in ('Prologue 1','Extra','Bonus','Oneshot','0A','Special 2','', '1.5'):
            row=bound([{'id':'id:'+label,'chapter':label}])
            effective=m.effective_output_metadata(row)
            self.assertEqual(effective['series_index'],1.5 if label=='1.5' else 1)
            flat=dict(effective,kind='chapter',chapter_number=label,volume=None)
            self.assertEqual(m.with_series_override(flat,{m.output_identity(row):67.5})['series_index_override'],67.5)
            self.assertEqual(row['chapter']['chapter'],label)

    def test_legacy_migration_preserves_unique_and_quarantines_ambiguity(self):
        a,b=bound([{'id':'a','chapter':'1'}]),bound([{'id':'b','chapter':'1'}])
        edits={('chapter',1.0):{'title':'Retained'}}
        unresolved=m.migrate_legacy_overrides([a,b],edits)
        self.assertEqual(unresolved,edits)
        self.assertNotIn(m.output_identity(a),edits)
        only={('chapter',1.0):{'title':'Unique','series_index':5}}
        self.assertEqual(m.migrate_legacy_overrides([a],only),{})
        self.assertEqual(only,{m.output_identity(a):{'title':'Unique','series_index':5}})
        foreign={('chapter',1.0):{'title':'Other provider edit'}}
        self.assertEqual(m.migrate_legacy_overrides([a],foreign,eligible=False),foreign)
        self.assertNotIn(m.output_identity(a),foreign)

    def test_local_reinspection_uses_validated_file_identity_not_random_import_uuid(self):
        def row(uuid):return dict(kind='import',import_id=uuid,book={'identity':['C:/fixture.cbz',500,1234]})
        self.assertEqual(m.output_identity(m.bind_output_identity(row('a'))),m.output_identity(m.bind_output_identity(row('b'))))

    def test_missing_exact_source_identity_fails_before_metadata_editing(self):
        with self.assertRaises(ValueError):bound([{'chapter':'1'}])

    def test_mutated_acquisition_payload_cannot_import_under_another_output_key(self):
        from calibre_plugins.manganana.books.imports.output_import import OutputImporter
        from unittest.mock import Mock
        row=bound([{'id':'exact-a','chapter':'1'}])
        row['output_acquisition']['members'][0][1]='different-source-record'
        db=Mock();db.all_book_ids.return_value=[]
        db.all_field_for.return_value={}
        with self.assertRaises(ValueError):OutputImporter(db).import_one(row,Mock())
        db.add_books.assert_not_called();db.find_identical_books.assert_not_called()

    def test_existing_volume_policy_uses_source_volume_not_user_index_or_chapter_index(self):
        import ast
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MangaNanaDialog')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('existing_volumes','existing_volume_ids','_existing_acquisition_volume')]
        ns={};exec(compile(ast.Module(body=methods,type_ignores=[]),'app/main.py','exec'),ns)
        values={10:dict(series='Berserk',series_index=1,identifiers={'mangaanka_output':'v2:owned','mangaanka_kind':'volume','mangaanka_volume':'5'}),
                11:dict(series='Berserk',series_index=1,identifiers={'mangaanka_output':'v2:chapter','mangaanka_kind':'chapter'}),
                12:dict(series='Berserk',series_index=9,identifiers={})}
        db=types.SimpleNamespace(all_book_ids=lambda:values,field_for=lambda f,b:values[b][f])
        owner=types.SimpleNamespace(db=db)
        if '_existing_acquisition_volume' in ns:owner._existing_acquisition_volume=lambda bid:ns['_existing_acquisition_volume'](owner,bid)
        self.assertEqual(ns['existing_volumes'](owner,'Berserk'),{5,9})
        self.assertEqual(ns['existing_volume_ids'](owner,'Berserk'),{5:10,9:12})

    def test_partial_volume_group_cannot_shadow_full_output_or_missing_format(self):
        import ast
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MangaNanaDialog')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('existing_volumes','_existing_acquisition_volume')]
        ns={};exec(compile(ast.Module(body=methods,type_ignores=[]),'app/main.py','exec'),ns)
        partial=bound([{'id':'source-a','chapter':'1'}],kind='volume',volume=1)
        full=bound([{'id':'source-a','chapter':'1'},{'id':'source-b','chapter':'2'}],kind='volume',volume=1)
        self.assertNotEqual(partial['output_identity'],full['output_identity'])
        values={1:dict(series='Berserk',series_index=67.5,identifiers={'mangaanka_output':partial['output_identity'],'mangaanka_kind':'volume','mangaanka_volume':'1'})}
        formats={1:{'CBZ'}}
        db=types.SimpleNamespace(all_book_ids=lambda:values,field_for=lambda f,b:values[b][f],has_format=lambda b,f:f in formats[b])
        owner=types.SimpleNamespace(db=db)
        owner._existing_acquisition_volume=lambda b:ns['_existing_acquisition_volume'](owner,b)
        lookup=lambda key,fmt:ns['existing_volumes'](owner,'Berserk',{key},fmt)
        self.assertEqual(set(),lookup(full['output_identity'],'cbz'))
        self.assertEqual({1},lookup(partial['output_identity'],'cbz'))
        self.assertEqual(set(),lookup(partial['output_identity'],'pdf'))
        values[2]=dict(series='Berserk',series_index=1,identifiers={'mangaanka_output':full['output_identity'],'mangaanka_kind':'volume','mangaanka_volume':'1'})
        formats[2]={'CBZ','PDF'}
        self.assertEqual({1},lookup(full['output_identity'],'pdf'))
        self.assertEqual({1},lookup(full['output_identity'],'cbz'))

if __name__=='__main__':unittest.main()
