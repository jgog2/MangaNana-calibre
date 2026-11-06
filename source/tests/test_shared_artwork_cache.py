"""Resource conservation, rendition safety and publication-context separation."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
import sqlite3,tempfile,threading,time,unittest,weakref,gc
from PIL import Image
from qt.core import QApplication
from calibre_plugins.manganana.books.imaging.artwork_cache import ArtworkResources,resource_identity,ResourceFailure,TTL
from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkCandidate,ArtworkResolver,prepare_artwork
from tests.test_patch1d_artwork import builder,md_art

def png(color,size=(440,600)):
    out=BytesIO();Image.new('RGB',size,color).save(out,'PNG');return out.getvalue()

class SharedArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance()or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=100.;self.cache=ArtworkResources(Path(self.temp.name)/'art.sqlite3',clock=lambda:self.now)
        self.addCleanup(self.drain)
        self.calls=[];self.provider=SimpleNamespace(source_id='mangapill',fetch_binary=lambda *a,**k:self.fail('wrong acquisition transport'))
        self.manifest=builder((1,)).apply_mangadex_artwork(md_art((1,))).build()
        self.url=self.manifest.volume('1').cover.url
        self.full=png('red');self.small=png('blue',(180,250));self.responses={self.url:self.full,self.url+'.256.jpg':self.small}
        def fetch(url,**kw):self.calls.append(url);return self.responses[url]
        self.resolver=ArtworkResolver(mangadex=SimpleNamespace(fetch_binary=fetch),resources=self.cache)
        self.resolver.register_manifest(self.manifest)
    def drain(self):
        worker=self.cache.writer
        if worker:worker.join(5);self.assertFalse(worker.is_alive())
    def test_changed_acquisition_fingerprints_reuse_qualified_display(self):
        first=self.resolver.candidates(self.url,self.provider)[0]
        a=self.resolver.resolve_display_url(self.url,self.provider)
        other=replace(self.manifest,runtime_publication={'source_fingerprints':{'weebcentral':'different'},'as_of':'new'})
        self.resolver.register_manifest(other);second=self.resolver.candidates(self.url,self.provider)[0]
        self.assertNotEqual(first.key,second.key);self.assertEqual(first.publication_key,second.publication_key)
        b=self.resolver.peek_display(self.url,SimpleNamespace(source_id='weebcentral'))
        self.assertEqual(a['artwork_key'],b['artwork_key']);self.assertEqual([self.url+'.256.jpg'],self.calls)
        self.assertEqual(1,self.cache.stats['image_decodes'])
    def test_display_rendition_never_becomes_output_original(self):
        display=self.resolver.resolve_display_url(self.url,self.provider)
        original=self.resolver.resolve_url(self.url,self.provider)
        self.assertEqual(self.full,original['raw']);self.assertNotEqual(self.full,display['raw'])
        self.assertEqual(self.small,self.cache.peek(resource_identity(replace(display['candidate'],url=self.url+'.256.jpg'))[0]).raw)
        self.assertEqual([self.url+'.256.jpg',self.url],self.calls)
        self.resolver.resolve_url(self.url,self.provider);self.assertEqual(2,len(self.calls))
    def test_publication_association_includes_edition_and_market(self):
        original=self.resolver.candidates(self.url,self.provider)[0].publication_key
        for edition in (replace(self.manifest.edition,identity='official_color'),replace(self.manifest.edition,market='US')):
            self.resolver.register_manifest(replace(self.manifest,edition=edition))
            self.assertNotEqual(original,self.resolver.candidates(self.url,self.provider)[0].publication_key)
    def test_cached_standard_does_not_replace_selected_colored_artwork(self):
        self.resolver.resolve_display_url(self.url,self.provider)
        selected=ArtworkCandidate('mangapill','https://provider.invalid/colored.png','1',publication_key='colored-approved')
        self.resolver.chains['selected']=(selected,)
        self.assertIsNone(self.resolver.peek_display('selected',self.provider))
    def test_disk_restart_validates_digest_and_avoids_network(self):
        self.resolver.resolve_display_url(self.url,self.provider);self.drain()
        reopened=ArtworkResources(self.cache.path,clock=lambda:self.now)
        resolver=ArtworkResolver(mangadex=SimpleNamespace(fetch_binary=lambda *a,**k:self.fail('unexpected network')),resources=reopened)
        resolver.register_manifest(self.manifest);result=resolver.resolve_display_url(self.url,self.provider)
        self.assertIsNotNone(result['image']);self.assertEqual(1,reopened.stats['disk_hit'])
    def test_expiry_and_clock_rollback_force_safe_refetch(self):
        self.resolver.resolve_display_url(self.url,self.provider);self.drain()
        self.now+=TTL+1;self.resolver.resolve_display_url(self.url,self.provider)
        self.assertEqual(2,len(self.calls));self.drain()
        self.now=0;self.resolver.resolve_display_url(self.url,self.provider);self.assertEqual(3,len(self.calls))
    def test_corrupt_blob_is_evicted_and_refetched(self):
        self.resolver.resolve_display_url(self.url,self.provider);self.drain()
        with closing(sqlite3.connect(self.cache.path))as db:
            db.execute("UPDATE resources SET raw=x'0001'");db.commit()
        reopened=ArtworkResources(self.cache.path,clock=lambda:self.now)
        candidate=self.resolver.candidates(self.url,self.provider)[0]
        value=reopened.acquire(replace(candidate,url=candidate.preview_url),lambda:self.small,prepare_artwork,lambda:False)
        self.assertEqual(self.small,value.raw);self.assertEqual(1,reopened.stats['disk_rejected'])
        if reopened.writer:reopened.writer.join(5)
    def test_corrupt_database_falls_back_to_memory_without_touching_other_data(self):
        self.cache.path.write_bytes(b'broken database')
        result=self.resolver.resolve_display_url(self.url,self.provider);self.drain()
        self.assertTrue(result['image']);self.assertTrue(self.cache.disk_disabled)
        self.assertEqual(b'broken database',self.cache.path.read_bytes())
    def test_signed_urls_and_userinfo_are_not_persisted(self):
        candidate=self.resolver.candidates(self.url,self.provider)[0]
        for tail in ('?token=private','?X-Amz-Signature=private','?key=private'):
            self.assertFalse(resource_identity(replace(candidate,url=self.url+tail))[1])
        a=replace(candidate,url='https://User:Secret@uploads.mangadex.org/a')
        b=replace(candidate,url='https://user:secret@uploads.mangadex.org/a')
        self.assertFalse(resource_identity(a)[1]);self.assertNotEqual(resource_identity(a)[0],resource_identity(b)[0])
    def test_provider_transport_is_not_shared_across_sources(self):
        a=ArtworkCandidate('mangapill','https://cdn.invalid/shared')
        self.assertNotEqual(resource_identity(a)[0],resource_identity(replace(a,source='weebcentral'))[0])
        self.assertEqual(resource_identity(ArtworkCandidate('mangadex',self.url))[0],resource_identity(ArtworkCandidate('mangadex_artwork',self.url))[0])
    def test_memory_and_disk_budgets(self):
        cache=ArtworkResources(Path(self.temp.name)/'budget.sqlite3',clock=lambda:self.now,memory_bytes=4000,disk_bytes=6000)
        base=self.resolver.candidates(self.url,self.provider)[0]
        for i in range(15):
            c=replace(base,url=self.url+str(i),publication_key='pub-'+str(i))
            cache.acquire(c,lambda:self.small,prepare_artwork,lambda:False)
        if cache.writer:cache.writer.join(5)
        self.assertLessEqual(cache.memory.bytes_used,4000);self.assertLessEqual(cache.pending_bytes,16*1024*1024)
        with closing(sqlite3.connect(cache.path))as db:self.assertLessEqual(db.execute('SELECT COALESCE(SUM(cost),0) FROM resources').fetchone()[0],6000)
    def test_no_orphan_long_lived_cache_writer(self):
        cache=ArtworkResources(Path(self.temp.name)/'lifetime.sqlite3')
        c=self.resolver.candidates(self.url,self.provider)[0]
        cache.acquire(c,lambda:self.small,prepare_artwork,lambda:False)
        if cache.writer:cache.writer.join(5)
        ref=weakref.ref(cache);del cache;gc.collect();self.assertIsNone(ref())
    def test_single_flight_and_independent_cancellation(self):
        candidate=self.resolver.candidates(self.url,self.provider)[0]
        entered=threading.Event();release=threading.Event();cancel=threading.Event();results=[];calls=[]
        def fetch():calls.append(1);entered.set();self.assertTrue(release.wait(3));return self.small
        def run(check):
            try:results.append(self.cache.acquire(candidate,fetch,prepare_artwork,check))
            except InterruptedError:results.append('cancelled')
        a=threading.Thread(target=run,args=(cancel.is_set,));a.start();self.assertTrue(entered.wait(2))
        b=threading.Thread(target=run,args=(lambda:False,));b.start()
        deadline=time.monotonic()+2
        while self.cache.stats['joined']<1 and time.monotonic()<deadline:time.sleep(.005)
        cancel.set();release.set();a.join(3);b.join(3)
        self.assertEqual(1,len(calls));self.assertIn('cancelled',results);self.assertEqual(1,sum(not isinstance(r,str)for r in results))
        self.assertFalse(self.cache.flights)
    def test_all_cancelled_subscribers_do_not_promote(self):
        cancelled=[False];c=self.resolver.candidates(self.url,self.provider)[0]
        def fetch():cancelled[0]=True;return self.small
        with self.assertRaises(InterruptedError):self.cache.acquire(c,fetch,prepare_artwork,lambda:cancelled[0])
        self.assertFalse(self.cache.memory);self.assertIsNone(self.cache.writer)
    def test_invalid_image_negative_cache_and_explicit_retry(self):
        candidate=self.resolver.candidates(self.url,self.provider)[0];calls=[]
        def fetch():calls.append(1);return b'not an image'
        for _ in range(2):
            with self.assertRaises(ResourceFailure):self.cache.acquire(candidate,fetch,prepare_artwork,lambda:False)
        self.assertEqual(1,len(calls));self.cache.retry(resource_identity(candidate)[0])
        self.assertEqual(self.small,self.cache.acquire(candidate,lambda:self.small,prepare_artwork,lambda:False).raw)
    def test_malformed_resource_url_is_a_bounded_failure(self):
        c=ArtworkCandidate('mangapill','https://[broken')
        self.assertFalse(resource_identity(c)[1])
        self.resolver.chains['broken']=(c,)
        self.assertIsNone(self.resolver.resolve_display_url('broken',self.provider)['raw'])
    def test_cache_writer_failure_is_terminal_and_does_not_fail_artwork(self):
        def fail(*_):raise OSError('storage unavailable')
        self.cache._write=fail
        result=self.resolver.resolve_display_url(self.url,self.provider);self.drain()
        self.assertIsNotNone(result['image']);self.assertTrue(self.cache.disk_disabled)
        self.assertIsNone(self.cache.writer);self.assertEqual(1,self.cache.stats['writer_unavailable'])
    def test_corrupt_decoded_preview_falls_back_without_uncaught_exception(self):
        from calibre_plugins.manganana.books.imaging.artwork_cache import Resource
        from hashlib import sha256
        c=self.resolver.candidates(self.url,self.provider)[0];variant=replace(c,url=c.preview_url)
        key=resource_identity(variant)[0]
        self.cache.memory[key]=Resource(key,self.small,b'broken PNG',sha256(self.small).hexdigest(),self.now)
        result=self.resolver.resolve_display_url(self.url,self.provider)
        self.assertIsNotNone(result['image']);self.assertEqual([self.url],self.calls)
        self.assertGreater(self.cache.stats['display_rejected'],0)
