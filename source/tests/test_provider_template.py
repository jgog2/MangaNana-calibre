"""Deterministic scaffold contract; no runtime registration or live requests."""
import unittest
from examples.provider_template import ExampleSource
from calibre_plugins.manganana.providers.source_adapter import acquire_volume_inventory
from calibre_plugins.manganana.providers.source_registry import SourceRegistry

URL='https://example.invalid/series/synthetic'
class ProviderTemplateTests(unittest.TestCase):
    def setUp(self):
        self.records=[dict(id='pre-a',chapter='Prologue 1',volume=None,title='Opening',pages=None),
                      dict(id='ordinary-a',chapter='1',volume=None,title='First',pages=1),
                      dict(id='ordinary-b',chapter='1',volume=None,title='Alternate release',pages=1)]
        self.calls=[]
        def transport(operation,reference):
            self.calls.append((operation,reference))
            return {'search':[dict(id='synthetic',url=URL,title='Synthetic',cover_url='')]*3,
                    'metadata':dict(uuid='synthetic',title='Synthetic',titles=[],author='',main_cover_url='',available_languages=['en']),
                    'chapters':self.records,'pages':{'full':['https://example.invalid/page/1.png'],'data_saver':[]},
                    'binary':b'controlled transport bytes'}[operation]
        self.source=ExampleSource(transport)
    def test_parse_and_isolated_registration(self):
        self.assertEqual(SourceRegistry([self.source]).identify(URL).reference,'synthetic')
        for url in ('https://other.invalid/series/a','https://u:p@example.invalid/series/a','https://example.invalid/page/a'):
            self.assertIsNone(self.source.parse_manga_ref(url))
    def test_search_pagination_and_metadata(self):
        page=self.source.search('Synthetic',limit=2)
        self.assertEqual((2,2,True),(len(page['rows']),page['next_offset'],page['has_more']))
        self.assertFalse(self.source.search('Synthetic',offset=2,limit=2)['has_more'])
        self.assertEqual('synthetic',self.source.get_manga(URL)['uuid'])
    def test_duplicate_labels_do_not_collapse_exact_records(self):
        rows=self.source.get_chapters(URL,'en');self.assertEqual(['pre-a','ordinary-a','ordinary-b'],[r['id'] for r in rows])
        self.assertEqual(['Prologue 1','1','1'],[r['chapter'] for r in rows])
    def test_inventory_capture_is_one_enumeration(self):
        plan,rows=acquire_volume_inventory(self.source,URL,'en')
        self.assertEqual(([],3),(plan['volumes'],len(rows)))
        self.assertEqual(1,sum(c[0]=='chapters' for c in self.calls))
    def test_complete_manifest_and_preview_contract(self):
        self.assertEqual(1,len(self.source.get_page_manifest('pre-a')['full']))
        self.assertEqual((b'controlled transport bytes',True),self.source.fetch_preview_page('', 'https://example.invalid/page/1.png',1))
    def test_failure_and_cancellation_are_not_empty_success(self):
        def failure(*a):raise RuntimeError('Controlled provider failure')
        with self.assertRaises(RuntimeError):ExampleSource(failure).get_chapters(URL,'en')
        def cancelled():raise InterruptedError('Cancelled')
        with self.assertRaises(InterruptedError):self.source.with_cancel_check(cancelled).get_manga(URL)
        bad=ExampleSource(lambda *a:{'full':[]})
        with self.assertRaises(ValueError):bad.get_page_manifest('x')
    def test_unknown_language_and_range_do_not_fabricate_membership(self):
        self.assertEqual([],self.source.get_chapters(URL,'ja'))
        self.assertEqual([],self.source.get_chapters(URL,'en',1,2))
