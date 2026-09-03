from pathlib import Path
import urllib.error
import unittest

from inventory_comparison import SourceInventory, compare_inventories, inspect_source_inventory
from source_registry import SourceRegistry
from weebcentral_source import WeebCentralAccessBlocked, WeebCentralSource

FIXTURES=Path(__file__).parent/'fixtures'


class Fetcher:
    def __init__(self): self.calls=[]; self.failures=[]
    def __call__(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if self.failures:
            failure=self.failures.pop(0)
            if failure: raise failure
        if 'search/simple' in url: return (FIXTURES/'weebcentral_search.html').read_text()
        if 'full-chapter-list' in url: return (FIXTURES/'weebcentral_chapters.html').read_text()
        if '/images?' in url: return (FIXTURES/'weebcentral_images.html').read_text()
        if '/chapters/' in url: return (FIXTURES/'weebcentral_reader.html').read_text()
        return (FIXTURES/'weebcentral_title.html').read_text()


class WeebCentralTests(unittest.TestCase):
    def setUp(self): self.fetch=Fetcher(); self.source=WeebCentralSource(fetch_text=self.fetch,sleeper=lambda _s:None)

    def test_registration_urls_and_capabilities(self):
        self.assertIs(self.source,SourceRegistry((self.source,)).get('weebcentral'))
        self.assertEqual('01J76XY7KWP8KX5RFGVZY5TR95',self.source.parse_manga_ref('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x'))
        self.assertIsNone(self.source.parse_manga_ref('https://example.com/series/01J76XY7KWP8KX5RFGVZY5TR95'))
        self.assertNotIn('volumes',self.source.capabilities)
        self.assertIn('direct_series',self.source.capabilities)
        self.assertIn('direct_chapters',self.source.capabilities)

    def test_search_uses_har_post_shape_and_parses_multiple_results(self):
        data=self.source.search('Attack on Titan')
        self.assertEqual(['Attack on Titan','Attack on Titan - Lost Girls'],[r['title'] for r in data['rows']])
        self.assertTrue(all(r['source_id']=='weebcentral' and r['source_name']=='WeebCentral' for r in data['rows']))
        self.assertTrue(data['rows'][0]['url'].endswith('/Shingeki-No-Kyojin'))
        self.assertTrue(data['rows'][0]['cover_url'].endswith('/cover/small/01J76XY7KWP8KX5RFGVZY5TR95.webp'))
        url,kwargs=self.fetch.calls[0]
        self.assertEqual('https://weebcentral.com/search/simple?location=main',url)
        self.assertEqual('POST',kwargs['method']); self.assertEqual(b'text=Attack%20on%20Titan',kwargs['data'])
        self.assertEqual(('true','quick-search-result','https://weebcentral.com/','application/x-www-form-urlencoded'),(
            kwargs['headers']['HX-Request'],kwargs['headers']['HX-Target'],kwargs['headers']['Referer'],kwargs['headers']['Content-Type']))
        self.assertNotIn('Cookie',kwargs['headers'])

    def test_metadata_chapters_pages_and_direct_chapter(self):
        md=self.source.get_manga('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/Shingeki-No-Kyojin')
        self.assertEqual(('Attack on Titan','ISAYAMA Hajime',2009,False),(md['title'],md['author'],md['year'],md['adult']))
        self.assertIn('Shingeki no Kyojin',md['alternate_titles'])
        self.assertEqual(('Manga','Complete',True), (md['type'],md['status'],md['official_translation']))
        self.assertEqual(['Action'],md['tags']); self.assertTrue(md['description'])
        self.assertTrue(md['main_cover_url'].endswith('/cover/normal/01J76XY7KWP8KX5RFGVZY5TR95.webp'))
        self.assertTrue(self.fetch.calls[0][0].endswith('/Shingeki-No-Kyojin'))
        chapters=self.source.get_chapters(md['source_url'],'en')
        self.assertEqual('1',chapters[0]['chapter']); self.assertEqual('139.5',chapters[-1]['chapter'])
        self.assertTrue(all(c['volume'] is None for c in chapters))
        chapter_call=next(call for call in self.fetch.calls if 'full-chapter-list' in call[0])
        self.assertEqual(('true','chapter-list',md['source_url']),(chapter_call[1]['headers']['HX-Request'],chapter_call[1]['headers']['HX-Target'],chapter_call[1]['headers']['Referer']))
        self.assertEqual([],self.source.get_download_plan(md['source_url'],'en',1,2)['volumes'])
        pages=self.source.get_page_manifest(chapters[0]['id'])['full']
        self.assertTrue(pages[0].endswith('-001.png')); self.assertTrue(pages[-1].endswith('-003.png'))
        page_call=next(call for call in self.fetch.calls if '/images?' in call[0])
        self.assertEqual(('true','chapter-images'),(page_call[1]['headers']['HX-Request'],page_call[1]['headers']['HX-Target']))
        chapter_url='https://weebcentral.com/chapters/01J76XYYRPD6MW53E6Y89K3NY5'
        self.assertEqual(md['uuid'],self.source.resolve_manga_ref(chapter_url))
        direct=self.source.get_manga(chapter_url)
        self.assertEqual(md['uuid'],direct['uuid'])
        self.assertTrue(direct['source_url'].endswith('/Shingeki-No-Kyojin'))

    def test_transient_503_retries_then_succeeds(self):
        self.fetch.failures=[urllib.error.HTTPError('u',503,'slow',{},None),urllib.error.HTTPError('u',503,'slow',{},None),None]
        self.assertEqual('Attack on Titan',self.source.get_manga('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x')['title'])
        self.assertEqual(3,len(self.fetch.calls))

    def test_retry_limit_permanent_failure_and_access_block_are_bounded(self):
        self.fetch.failures=[urllib.error.HTTPError('u',503,'slow',{},None)]*3
        with self.assertRaisesRegex(RuntimeError,'after 3 attempt'):
            self.source.get_manga('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x')
        self.assertEqual(3,len(self.fetch.calls))

        fetch=Fetcher(); fetch.failures=[urllib.error.HTTPError('u',404,'missing',{},None)]
        with self.assertRaises(urllib.error.HTTPError):
            WeebCentralSource(fetch_text=fetch,sleeper=lambda _s:None).get_manga('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x')
        self.assertEqual(1,len(fetch.calls))

        fetch=Fetcher(); fetch.failures=[urllib.error.HTTPError('u',403,'blocked',{},None)]
        with self.assertRaisesRegex(WeebCentralAccessBlocked,'site protection'):
            WeebCentralSource(fetch_text=fetch,sleeper=lambda _s:None).search('Attack on Titan')
        self.assertEqual(1,len(fetch.calls))

        calls=[]
        def invalid(url,**kwargs): calls.append(url); return '<html>invalid title response</html>'
        with self.assertRaisesRegex(RuntimeError,'did not contain metadata'):
            WeebCentralSource(fetch_text=invalid,sleeper=lambda _s:None).get_manga('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x')
        self.assertEqual(1,len(calls))

    def test_cancellation_interrupts_retry_backoff(self):
        fetch=Fetcher(); fetch.failures=[urllib.error.HTTPError('u',503,'slow',{},None)]
        checks=[]
        def cancel_check():
            checks.append(True)
            if len(checks) >= 2: raise InterruptedError('cancelled')
        source=WeebCentralSource(fetch_text=fetch,cancel_check=cancel_check,sleeper=lambda _s:None)
        with self.assertRaises(InterruptedError): source.search('Attack on Titan')
        self.assertEqual(1,len(fetch.calls))

    def test_special_chapter_is_retained_after_numeric_inventory(self):
        base=(FIXTURES/'weebcentral_chapters.html').read_text()
        special='<a href="/chapters/01J76XZ2TJFTV49EDXRXNDAWAA"><span class="">Episode Special</span></a>'
        source=WeebCentralSource(fetch_text=lambda url,**kwargs: base+special,sleeper=lambda _s:None)
        chapters=source.get_chapters('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x','en')
        self.assertEqual('Special',chapters[-1]['chapter'])

    def test_current_chapter_link_shape_does_not_require_empty_span_class(self):
        live_shape='''
        <a class="flex" href="/chapters/01KXB61AGDZFBRTF58GHJNB6V8">
          <span class="font-medium">Chapter 160</span>
          <time>Last Read 2026-07-12T12:50:03Z</time>
        </a>
        '''
        source=WeebCentralSource(fetch_text=lambda _url,**_kwargs:live_shape,sleeper=lambda _s:None)
        rows=source.get_chapters('https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x','en')
        self.assertEqual(['160'],[row['chapter'] for row in rows])
        self.assertEqual(('en',),source.content_languages)

    def test_chapter_ranking_and_volume_projection_qualification(self):
        candidate={'source_id':'weebcentral','source_name':'WeebCentral','id':'wc','url':'https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/x','title':'Attack on Titan'}
        inventory=inspect_source_inventory(self.source,candidate,'en')
        self.assertTrue(inventory.usable); self.assertEqual(0,inventory.native_volumes)
        self.assertEqual(inventory.chapter_count,inventory.standalone_chapters)
        self.assertIs(compare_inventories((inventory,),workflow='chapter').selected,inventory)
        self.assertIs(compare_inventories((inventory,),workflow='volume').selected,inventory)
        smaller=SourceInventory('mangapill','MangaPill',{'url':'pill'},'en','original',True,standalone_chapters=2,chapter_count=2,usable=True,complete=True)
        self.assertEqual('weebcentral',compare_inventories((smaller,inventory),workflow='chapter').selected.source_id)


if __name__=='__main__': unittest.main()
