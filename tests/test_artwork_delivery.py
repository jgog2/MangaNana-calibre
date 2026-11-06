"""Patch 1E deterministic delivery fixtures; no network or manga image assets.

Synthetic denial pixels exercise the exact production signature gate. The live
capture test additionally checks the actual signature when PATCH1E_DENIAL_FILE
is supplied; this private test artifact is never bundled in the plugin/repo.
"""
import ast
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import os
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image, ImageOps
from calibre_plugins.manganana.books.imaging import artwork_delivery as delivery
from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkCandidate as C, ArtworkResolver, validate_artwork
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from tests.test_patch1d_artwork import builder, md_art, book, cover
from tests.test_patch1b_search import source as atsu, FIX as ATSU
from tests.test_mangadex_structure_reference import project


def png(color='orange', size=(48,72)):
    out=BytesIO(); Image.new('RGB',size,color).save(out,'PNG'); return out.getvalue()


DENIAL=png('purple',(600,642))
GOOD=png()
BW=png('blue')
SYNTHETIC_SIGNATURE=sha256(Image.open(BytesIO(DENIAL)).tobytes()).hexdigest()


def chain(volume='22'):
    return (C('mangadex_artwork','https://uploads.mangadex.org/covers/test/'+volume+'.jpg',volume),
            C('bookwalker','https://c.bookwalker.jp/'+volume+'.jpg',volume),
            C('google_books','https://books.google.com/'+volume+'.jpg',volume))


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.signature=patch.object(delivery,'MANGADEX_DENIAL_RGB',SYNTHETIC_SIGNATURE)
        self.signature.start();self.addCleanup(self.signature.stop)
        self.calls=[];self.responses={};self.now=0
        def fetch(source,url):
            self.calls.append((source,url))
            value=self.responses.get(url,GOOD)
            if isinstance(value,Exception): raise value
            if callable(value):return value()
            return value
        self.provider=SimpleNamespace(source_id='mangak',fetch_binary=lambda url,**kw:fetch('provider',url))
        md=SimpleNamespace(fetch_binary=lambda url,**kw:fetch('mangadex_artwork',url))
        self.resolver=ArtworkResolver(md,lambda url:fetch('reference',url),lambda:self.now)
        self.chain=chain()
        self.responses[self.chain[1].url]=BW

    def resolve(self,candidates=None,**kw):return self.resolver.resolve(candidates or self.chain,self.provider,**kw)

    def test_valid_mangadex_wins_lazily(self):
        result=self.resolve();self.assertEqual('mangadex_artwork',result['candidate'].source)
        self.assertEqual(1,len(self.calls));self.assertEqual(GOOD,result['raw'])

    def test_known_placeholder_falls_through(self):
        self.responses[self.chain[0].url]=DENIAL
        result=self.resolve();self.assertEqual(BW,result['raw']);self.assertEqual('bookwalker',result['candidate'].source)
        self.assertEqual((('mangadex_artwork','known placeholder'),),result['failures'])

    def test_response_order_does_not_change_placeholder_detection(self):
        for blobs in ((DENIAL,GOOD),(GOOD,DENIAL)):
            self.assertEqual([b==DENIAL for b in blobs],[validate_artwork(b)=='known placeholder' for b in blobs])

    def test_decoded_hash_rejects_lossless_reencoding(self):
        output=BytesIO();Image.open(BytesIO(DENIAL)).save(output,'BMP')
        self.assertNotEqual(DENIAL,output.getvalue());self.assertEqual('known placeholder',validate_artwork(output.getvalue()))

    def test_dimensions_alone_never_reject(self):
        self.assertEqual('',validate_artwork(png('white',(600,642))))

    def test_unusual_valid_covers_are_accepted(self):
        for color,size in [('white',(4,400)),('black',(400,4)),('red',(600,642))]:
            self.assertEqual('',validate_artwork(png(color,size)))

    def test_network_and_decode_failure_matrix(self):
        for failure in (TimeoutError(),HTTPError('u',403,'denied',{},None),HTTPError('u',404,'missing',{},None),
                        b'<html>error</html>',b'not an image',b'',DENIAL):
            with self.subTest(failure=type(failure).__name__):
                self.resolver.valid.clear();self.resolver.negative.clear();self.calls.clear()
                self.responses[self.chain[0].url]=failure
                self.assertEqual('bookwalker',self.resolve()['candidate'].source)
                self.assertEqual(2,len(self.calls))

    def test_google_third_level(self):
        self.responses.update({self.chain[0].url:DENIAL,self.chain[1].url:TimeoutError()})
        self.assertEqual('google_books',self.resolve()['candidate'].source);self.assertEqual(3,len(self.calls))

    def test_all_fail_no_cover(self):
        self.responses.update({c.url:DENIAL for c in self.chain})
        self.assertIsNone(self.resolve()['raw']);self.assertFalse(self.resolver.valid)

    def test_selected_provider_valid_wins(self):
        selected=C('mangak','https://mangak.io/exact.jpg','22')
        self.assertEqual('mangak',self.resolve((selected,)+self.chain)['candidate'].source)
        self.assertEqual([('provider',selected.url)],self.calls)

    def test_selected_provider_invalid_falls_through(self):
        selected=C('mangak','https://mangak.io/exact.jpg','22');self.responses[selected.url]=b'bad'
        self.assertEqual('mangadex_artwork',self.resolve((selected,)+self.chain)['candidate'].source)

    def test_reference_never_uses_acquisition_transport(self):
        for source in ('mangak','atsu','mangapill','weebcentral'):
            self.provider.source_id=source;self.resolver.valid.clear()
            self.provider.fetch_binary=lambda *a,**kw:self.fail('Acquisition transport leaked')
            self.assertEqual('mangadex_artwork',self.resolve()['candidate'].source)
            self.assertEqual('bookwalker',self.resolve(self.chain[1:])['candidate'].source)

    def test_valid_cache_keeps_winner_not_failed_bytes(self):
        self.responses[self.chain[0].url]=DENIAL
        a=self.resolve();b=self.resolve()
        self.assertEqual(a,b);self.assertEqual(2,len(self.calls))
        self.assertNotIn(self.chain[0].key,self.resolver.valid)
        self.assertEqual(BW,self.resolver.valid[self.chain[1].key])
        self.assertEqual('bookwalker',self.resolver.winners['22'].source)

    def test_negative_cache_expires_and_does_not_permanently_blacklist(self):
        self.responses[self.chain[0].url]=DENIAL;self.resolve()
        self.responses[self.chain[0].url]=GOOD;self.now=61
        self.assertEqual('mangadex_artwork',self.resolve()['candidate'].source)

    def test_negative_cache_is_bounded(self):
        for i in range(280):
            c=C('mangak','https://mangak.io/'+str(i));self.responses[c.url]=b'bad';self.resolve((c,))
        self.assertEqual(256,len(self.resolver.negative))

    def test_cancel_before_fetch(self):
        with self.assertRaises(InterruptedError):self.resolve(cancelled=lambda:True)
        self.assertFalse(self.calls)

    def test_cancel_during_fetch_prevents_fallback_and_cache(self):
        cancelled=[False]
        def interrupted():cancelled[0]=True;return DENIAL
        self.responses[self.chain[0].url]=interrupted
        with self.assertRaises(InterruptedError):self.resolve(cancelled=lambda:cancelled[0])
        self.assertEqual(1,len(self.calls));self.assertFalse(self.resolver.valid);self.assertFalse(self.resolver.negative)

    def test_cancel_after_valid_fetch_prevents_promotion(self):
        cancelled=[False]
        def interrupted():cancelled[0]=True;return GOOD
        self.responses[self.chain[0].url]=interrupted
        with self.assertRaises(InterruptedError):self.resolve(cancelled=lambda:cancelled[0])
        self.assertFalse(self.resolver.valid);self.assertFalse(self.resolver.winners)

    def test_concise_logs_only_for_fallback(self):
        log=[];self.resolve(log=log.append);self.assertFalse(log)
        self.resolver.valid.clear();self.responses[self.chain[0].url]=DENIAL
        self.resolve(log=log.append);self.assertEqual(1,len(log));self.assertIn('bookwalker',log[0])
        self.assertNotIn('https:',log[0]);self.assertNotIn(SYNTHETIC_SIGNATURE,log[0])

    def test_candidate_chains_retain_all_priorities_in_any_apply_order(self):
        for reverse in (False,True):
            b=builder((1,));actions=[lambda:b.apply_provider_covers({1:'https://mangak/1'},'mangak'),
                lambda:b.apply_mangadex_artwork(md_art((1,))),lambda:b.apply_bookwalker(book((1,))),
                lambda:b.apply_google_books({'covers':[cover('google_books',1)]})]
            for action in reversed(actions) if reverse else actions:action()
            volume=b.build().volume('1')
            self.assertEqual(['mangak','mangadex_artwork','bookwalker','google_books'],[a.source for a in volume.artwork_candidates])
            self.assertEqual('mangak',volume.cover.source)

    def test_registration_preserves_full_provenance_and_fallback_aliases(self):
        b=builder((1,)).apply_mangadex_artwork(md_art((1,))).apply_bookwalker(book((1,)))
        manifest=b.build();self.resolver.register_manifest(manifest)
        md,bw=manifest.volume('1').artwork_candidates
        self.assertEqual(self.resolver.candidates(md.url,self.provider),self.resolver.candidates(bw.url,self.provider))
        self.assertEqual(md.identity,self.resolver.candidates(md.url,self.provider)[0].source_identity)

    def test_banana_19_native_ids_unchanged_with_per_volume_fallback(self):
        source=atsu();rows=source.get_chapters('https://atsu.moe/manga/W6oyN','en')
        before=[dict(row) for row in rows];plan=source.get_download_plan('https://atsu.moe/manga/W6oyN','en')
        for n in range(1,20):
            candidates=chain(str(n));self.responses[candidates[0].url]=DENIAL if n in (1,7,19) else GOOD
            self.assertEqual('bookwalker' if n in (1,7,19) else 'mangadex_artwork',self.resolve(candidates)['candidate'].source)
        self.assertEqual(before,rows);self.assertEqual(list(range(1,20)),plan['volumes']);self.assertEqual(0,plan['bonus_chapters'])
        self.assertEqual({r['id'] for r in ATSU['banana_chapters']['chapters']},{r['id'].split('/')[-1] for r in rows})

    def test_world_structure_163_and_only_bad_volume_falls_back(self):
        rows,projection,plan=project('mangak')
        self.assertEqual(163,len(rows));self.assertEqual(14,len(plan['volumes']))
        self.assertEqual(0,plan['unmapped_chapter_count'])
        before=[dict(r) for r in rows]
        for n in range(1,15):
            candidates=chain(str(n));self.responses[candidates[0].url]=DENIAL if n==6 else GOOD
            self.assertEqual('bookwalker' if n==6 else 'mangadex_artwork',self.resolve(candidates)['candidate'].source)
        self.assertEqual(before,list(rows))

    def test_jojolion_preview_and_real_output_metadata_use_same_bw_bytes(self):
        from tests.test_empress_pipeline import production_namespace, Source
        namespace=production_namespace();namespace['ImageOps']=ImageOps
        node=next(n for n in ast.parse(Path('app/main.py').read_text(encoding='utf-8')).body
                  if isinstance(n,ast.ClassDef) and n.name=='CoverPreviewWorker')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app/main.py','exec'),namespace)
        self.responses[self.chain[0].url]=DENIAL
        self.resolver.chains[self.chain[0].url]=self.chain
        worker=namespace['CoverPreviewWorker'](self.provider,self.chain[0].url,
            dict(mode='keep'),artwork_resolver=self.resolver)
        worker.run();self.assertFalse(worker.failed.calls)
        self.assertEqual('bookwalker',worker.artwork_candidate.source)
        self.assertEqual(Image.open(BytesIO(BW)).tobytes(),Image.open(BytesIO(worker.ready.calls[0][0])).tobytes())
        source=Source();source.source_id='mangak'
        for fmt in ('cbz',):
            output=namespace['DownloadWorker'](source,'url','JoJolion','Creator','Series','en',22,22,
                True,True,(),artwork_resolver=self.resolver,output_format=fmt)
            state=dict(bytes=0,pages_done=0,pages_total=3,volume_done=0,started=time.time())
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/('volume.'+fmt)
                cover_path=output._download_group([{'id':'original-mangak-reader','chapter':'88','pages':3}],
                    path,'JoJolion',22,self.chain[0].url,state,1,1,3)
                self.assertEqual(BW,Path(cover_path).read_bytes())
                self.assertEqual('bookwalker',output.artwork_provenance[22].source)
                self.assertTrue(path.stat().st_size)
                if fmt=='cbz':
                    with zipfile.ZipFile(path) as archive:
                        self.assertEqual(3,len([n for n in archive.namelist() if n.endswith('.png')]))
        self.assertEqual(2,len(self.calls))  # Preview/output reuse validated resolution.

    def test_all_fail_real_downloader_omits_metadata_cover(self):
        from tests.test_empress_pipeline import production_namespace, Source
        self.responses.update({c.url:b'bad' for c in self.chain});self.resolver.chains[self.chain[0].url]=self.chain
        namespace=production_namespace();source=Source();source.source_id='mangak'
        worker=namespace['DownloadWorker'](source,'url','Title','Creator','Series','en',22,22,
            True,True,(),artwork_resolver=self.resolver)
        state=dict(bytes=0,pages_done=0,pages_total=3,volume_done=0,started=time.time())
        with tempfile.TemporaryDirectory() as directory:
            result=worker._download_group([{'id':'original-reader','chapter':'88','pages':3}],
                Path(directory)/'out.cbz','Title',22,self.chain[0].url,state,1,1,3)
            self.assertIsNone(result);self.assertFalse(list(Path(directory).glob('*_cover*')))

    def test_thumbnail_worker_resolves_fallback_and_sizes_pixels_off_gui_thread(self):
        from threading import RLock
        from collections import deque
        from tests.test_empress_pipeline import production_namespace
        namespace=production_namespace();namespace['ImageOps']=ImageOps
        namespace.update(RLock=RLock,deque=deque)
        class Thread(namespace['QThread']):
            def __init__(self,parent=None):super().__init__()
        namespace['QThread']=Thread
        body=ast.parse(Path('app/main.py').read_text(encoding='utf-8')).body
        budget=next(n for n in body if isinstance(n,ast.Assign)and
            any(isinstance(target,ast.Name)and target.id=='COVER_BATCH_LIMIT'for target in n.targets))
        node=next(n for n in body
                  if isinstance(n,ast.ClassDef) and n.name=='ImageBatchWorker')
        exec(compile(ast.Module(body=[budget,node],type_ignores=[]),'app/main.py','exec'),namespace)
        self.responses[self.chain[0].url]=DENIAL
        full=png('blue',(440,900));self.responses[self.chain[1].url]=full
        self.resolver.chains[self.chain[0].url]=self.chain
        worker=namespace['ImageBatchWorker'](('volume',1,1),[(self.chain[0].url,[])],
            source=self.provider,artwork_resolver=self.resolver)
        worker.run();result=worker.image_ready.calls[0][0]
        self.assertEqual('bookwalker',result['candidate'].source)
        self.assertEqual((147,300),Image.open(BytesIO(result['raw'])).size)
        self.assertEqual(full,self.resolver.valid[self.chain[1].key])
        self.assertEqual(2,len(self.calls));self.assertFalse(worker.image_failed.calls)


class TransportTests(unittest.TestCase):
    def test_neutral_and_native_mangadex_headers_are_acquisition_independent(self):
        requests=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return GOOD
        def request(req,**kw):requests.append(dict(req.header_items()));return Response()
        with patch('urllib.request.urlopen',request):
            for source in ('mangak','atsu','mangapill'):
                provider=SimpleNamespace(source_id=source,fetch_binary=lambda *a,**k:self.fail('provider used'))
                resolver=ArtworkResolver()
                resolver.resolve(chain()[:1],provider)
                resolver.resolve(chain()[1:],provider)
        self.assertEqual(requests[:2],requests[2:4]);self.assertEqual(requests[:2],requests[4:])
        for headers in requests:
            self.assertEqual({'user-agent','accept'},{k.lower() for k in headers})
        self.assertEqual('*/*',requests[0]['Accept'])

    def test_legacy_reference_urls_route_by_host(self):
        provider=SimpleNamespace(source_id='atsu')
        for url,source in [('https://uploads.mangadex.org/a','mangadex_artwork'),('https://c.bookwalker.jp/a','bookwalker'),
                           ('https://books.google.com/a','google_books')]:
            self.assertEqual(source,delivery.candidate_for_url(url,provider).source)

    @unittest.skipUnless(os.environ.get('PATCH1E_DENIAL_FILE'),'Private live denial capture not supplied')
    def test_real_captured_denial_and_lossless_reencoding(self):
        raw=Path(os.environ['PATCH1E_DENIAL_FILE']).read_bytes()
        self.assertEqual('known placeholder',validate_artwork(raw))
        out=BytesIO();Image.open(BytesIO(raw)).save(out,'PNG')
        self.assertEqual('known placeholder',validate_artwork(out.getvalue()))


if __name__=='__main__':unittest.main()
