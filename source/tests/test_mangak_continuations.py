"""Synthetic pixels only; exact-manifest reconstruction and no-op controls."""
from copy import deepcopy
import hashlib
from io import BytesIO
import os
from unittest.mock import patch
import unittest

from PIL import Image
from calibre_plugins.manganana.providers import mangak_continuations as layouts
from calibre_plugins.manganana.providers.mangak_source import MangaKSource

FLAG='MANGAANKA_MANGAK_CONTINUATIONS_ENABLED'
URL='https://mangak.io/haikyu/chapter-2-1'


def synthetic_capture():
    """Scaled test strips with unique pixels; last unit stands for the profile."""
    blobs={}; fragments=[]; expected=[]
    for n in range(20):
        images=[]
        for footer in (False,True):
            image=Image.new('RGB',(20,2 if footer else 30),(n*10+5,80 if footer else 20,100))
            image.putpixel((n%20,0),(255,255,255))
            images.append(image)
            stream=BytesIO(); image.save(stream,'PNG'); blob=stream.getvalue()
            url=f'https://fixture.invalid/fragment-{len(fragments)+1}.png'; blobs[url]=blob
            fragments.append({'url':url,'width':image.width,'height':image.height,'sha256':hashlib.sha256(blob).hexdigest()})
        page=Image.new('RGB',(20,32)); page.paste(images[0],(0,0)); page.paste(images[1],(0,30))
        expected.append(page)
        for image in images: image.close()
    recipe={'provider_record_id':'D6jMm9xD','reader_url':URL,'fragments':fragments,'review_basis':'SYNTHETIC TEST ONLY'}
    reader={'id':'D6jMm9xD','url':'/haikyu/chapter-2-1','images':list(blobs),
            'pages':[{k:f[k] for k in ('url','width','height')} for f in fragments]}
    return recipe,reader,blobs,expected


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.recipe,self.reader,self.blobs,self.expected=synthetic_capture()
        self.patch=patch.object(layouts,'reviewed_layouts',return_value=(self.recipe,)); self.patch.start()
        self.env=patch.dict(os.environ,{FLAG:'1'}); self.env.start()
        self.calls=[]
        def fetch(url,**kwargs): self.calls.append(url); return self.blobs[url]
        self.source=MangaKSource(fetch_binary=fetch)
        self.source._page_props=lambda url:{'initialChapter':self.reader}
    def tearDown(self):
        self.env.stop(); self.patch.stop()
        for image in self.expected: image.close()

    def test_all_fragments_and_profile_preserved_in_order_without_resampling(self):
        pages=self.source.get_page_manifest(URL)['full']; self.assertEqual(20,len(pages))
        for url,expected in zip(pages,self.expected):
            with Image.open(BytesIO(self.source.fetch_binary(url))) as image:
                self.assertEqual(expected.size,image.size); self.assertEqual(expected.tobytes(),image.tobytes())
        self.assertEqual(list(self.blobs),self.calls)
        self.assertEqual(195,self.expected[-1].getpixel((0,31))[0])  # Attached profile footer, not dropped.

    def test_disabled_manifest_and_binary_identical(self):
        os.environ[FLAG]='0'
        self.assertEqual(list(self.blobs),self.source.get_page_manifest(URL)['full'])
        for url,blob in self.blobs.items(): self.assertEqual(blob,self.source.fetch_binary(url))

    def test_ordinary_reader_not_reconstructed_even_with_matching_dimensions(self):
        self.reader['id']='ordinary'; self.reader['url']='/haikyu/chapter-3'
        self.assertEqual(list(self.blobs),self.source.get_page_manifest('https://mangak.io/haikyu/chapter-3')['full'])

    def test_known_url_with_different_record_fails(self):
        self.reader['id']='changed'
        with self.assertRaisesRegex(ValueError,'manifest changed'): self.source.get_page_manifest(URL)

    def test_known_record_with_changed_reader_fails(self):
        self.reader['url']='/haikyu/chapter-3'
        with self.assertRaisesRegex(ValueError,'manifest changed'):
            self.source.get_page_manifest('https://mangak.io/haikyu/chapter-3')

    def test_changed_order_truncation_and_geometry_fail_before_image_fetch(self):
        original=deepcopy(self.reader)
        for mutation in ('order','truncated','geometry'):
            self.reader=deepcopy(original)
            if mutation=='order': self.reader['pages'].reverse(); self.reader['images'].reverse()
            elif mutation=='truncated': self.reader['pages'].pop(); self.reader['images'].pop()
            else: self.reader['pages'][0]['height']+=1
            with self.assertRaisesRegex(ValueError,'manifest changed'): self.source.get_page_manifest(URL)
        self.assertEqual([],self.calls)

    def test_changed_bytes_fail_closed(self):
        page=self.source.get_page_manifest(URL)['full'][0]
        self.blobs[next(iter(self.blobs))]=b'changed'
        with self.assertRaisesRegex(ValueError,'bytes changed'): self.source.fetch_binary(page)

    def test_invalid_geometry_with_matching_hash_still_fails(self):
        self.recipe['fragments'][0]['width']+=1
        page=f'{layouts.SCHEME}://{layouts._key(self.recipe)}/0.png'
        with self.assertRaisesRegex(ValueError,'geometry changed'): self.source.fetch_binary(page)

    def test_preview_uses_same_reconstruction(self):
        page=self.source.get_page_manifest(URL)['full'][0]
        blob,full=self.source.fetch_preview_page(None,page,0)
        self.assertTrue(full)
        with Image.open(BytesIO(blob)) as image: self.assertEqual(self.expected[0].tobytes(),image.tobytes())

    def test_cancel_between_fragment_requests(self):
        page=self.source.get_page_manifest(URL)['full'][0]
        def cancel():
            if self.calls: raise InterruptedError('cancel')
        source=self.source.with_cancel_check(cancel)
        with self.assertRaises(InterruptedError): source.fetch_binary(page)
        self.assertEqual(1,len(self.calls))

    def test_unknown_internal_page_and_disabled_handle_fail(self):
        with self.assertRaises(ValueError): self.source.fetch_binary(layouts.SCHEME+'://unknown/0.png')
        page=self.source.get_page_manifest(URL)['full'][0]; os.environ[FLAG]='0'
        with self.assertRaises(ValueError): self.source.fetch_binary(page)

    def test_opaque_record_and_original_label_retained_by_adapter(self):
        self.source._title=lambda value:({'id':'title'},'https://mangak.io/haikyu')
        self.source._json=lambda value:{'data':{'chapters':[{'id':'D6jMm9xD','name':'Chapter 2.1',
                                                           'url':'/haikyu/chapter-2-1','number':6}]}}
        row=self.source.get_chapters('https://mangak.io/haikyu','en')[0]
        self.assertEqual(URL,row['id']); self.assertEqual('2.1',row['chapter'])
        self.assertEqual('D6jMm9xD',row['_provider_record_id']); self.assertEqual('Chapter 2.1',row['_provider_label'])

    def test_catalog_reader_identity_checked_even_with_strips_disabled(self):
        os.environ[FLAG]='0'
        self.assertEqual(40,len(self.source.get_page_manifest(URL,expected_record_id='D6jMm9xD')['full']))
        self.reader['id']='replacement-record'
        with self.assertRaisesRegex(ValueError,'reader record ID differs'):
            self.source.get_page_manifest(URL,expected_record_id='D6jMm9xD')
        self.assertEqual([],self.calls)

    def test_catalog_reader_missing_identity_fails_before_fetch(self):
        os.environ[FLAG]='0'; del self.reader['id']
        with self.assertRaisesRegex(ValueError,'reader record ID differs'):
            self.source.get_page_manifest(URL,expected_record_id='D6jMm9xD')
        self.assertEqual([],self.calls)


class PackagedContinuationEvidenceTests(unittest.TestCase):
    def test_reviewed_resource_is_complete_and_contains_no_mapping(self):
        recipes=layouts.reviewed_layouts(); self.assertEqual(1,len(recipes))
        recipe=recipes[0]; self.assertEqual('D6jMm9xD',recipe['provider_record_id'])
        self.assertEqual(40,len(recipe['fragments']))
        for n,fragment in enumerate(recipe['fragments']):
            self.assertEqual((1067,100 if n%2 else 1500),(fragment['width'],fragment['height']))
            self.assertEqual(64,len(fragment['sha256']))
        self.assertNotIn('chapter_id',recipe); self.assertNotIn('volume',recipe)

    def test_new_runtime_module_and_evidence_resource_packaged(self):
        from tools.build_plugin import files_to_package
        from pathlib import Path
        names={name for _,name in files_to_package(Path(__file__).resolve().parents[1])}
        self.assertTrue({'providers/mangak_continuations.py',layouts.RESOURCE} <= names)
        self.assertFalse(any('haikyu_catalog' in name for name in names))


if __name__=='__main__': unittest.main()
