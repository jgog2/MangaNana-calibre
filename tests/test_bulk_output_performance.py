"""Bulk identity conservation against the frozen r4 implementation."""
import dataclasses
import random
import sys
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from calibre_plugins.manganana.books.output import chapter_output as current

ROOT=Path(__file__).resolve().parents[1]


class BulkEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT/'dist/MangaAnka-v0.14.0-dev-final-qualification-r4-test.zip').is_file():
            raise unittest.SkipTest('Frozen r4 package is retained privately; current-source controls run separately')
        module=types.ModuleType('bulk_evidence_r4');module.__package__=''
        sys.modules[module.__name__]=module
        with zipfile.ZipFile(ROOT/'dist/MangaAnka-v0.14.0-dev-final-qualification-r4-test.zip') as archive:
            exec(compile(archive.read('books/output/chapter_output.py'),'r4/chapter_output.py','exec'),module.__dict__)
        cls.before=module

    def test_index_preserves_conflicts_titles_namespaces_and_provenance(self):
        rng=random.Random(4014)
        for case in range(45):
            selected=[dict(id=str(i),chapter=rng.choice(('0','1','1.5','2','3','Extra','Prologue 1')),
                volume=rng.choice((None,'1','2')),title=rng.choice(('','Title','OTHER','日本語')),
                numbering_group=rng.choice(('','main','prologue')),_source_id='primary') for i in range(15)]
            sources=[dict(source_id=sid,work_id=work,edition=edition,chapters=[
                dict(row,id='e-'+str(n),volume=rng.choice((None,'1','2','3')))
                for n,row in enumerate(rng.choices(selected,k=35))])
                for sid,work,edition in (('primary','work','original'),('secondary','work','original'),
                    ('other','contradiction','original'),('colored','work','official_color'))]
            kwargs=dict(page_source_id='primary',page_work_id='work',page_edition='original')
            with self.subTest(case=case):
                self.assertEqual(dataclasses.asdict(self.before.resolve_volume_evidence(selected,sources,**kwargs)),
                    dataclasses.asdict(current.resolve_volume_evidence(selected,sources,**kwargs)))

class CurrentBulkTests(unittest.TestCase):
    def test_identity_normalization_is_linear_in_large_inventory(self):
        rows=[dict(id=str(i),chapter=str(i),volume=str(i//10+1),title='Chapter '+str(i)) for i in range(1169)]
        source=current.VolumeEvidenceSource('primary','work','original',tuple(rows))
        with patch.object(current,'chapter_identity',wraps=current.chapter_identity) as identity:
            result=current.resolve_volume_evidence(rows,(source,),page_source_id='primary',page_work_id='work')
        self.assertEqual(len(result.assignments),1169)
        self.assertLessEqual(identity.call_count,2*len(rows))
        self.assertEqual(tuple(str(i) for i in range(1169)),tuple(k for k,v in result.assignments))
