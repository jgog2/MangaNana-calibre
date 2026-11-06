"""Bounded typed chapter metadata supplements aggregate structure safely."""
from copy import deepcopy
import unittest
from concurrent.futures import CancelledError
from urllib.parse import urlparse, parse_qs
from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver

MID='11111111-1111-1111-1111-111111111111'
CID='22222222-2222-2222-2222-222222222222'
EVIDENCE=dict(canonical_work_id='fixture:work',canonical_title='Fixture',identity_confidence='high',
              edition_profile='standard',mangadex_title_ids=[MID],media_type='manga')
AGGREGATE=dict(result='ok',volumes={'1':dict(volume='1',chapters={'2.5':dict(chapter='2.5',id=CID,others=[])})})
METADATA=dict(result='ok',data=[dict(id=CID,type='chapter',attributes=dict(chapter='2.5',volume='1',title='Omake & Extras',translatedLanguage='pt-br'),relationships=[dict(type='manga',id=MID)])])

class MangaDexSpecialMetadata(unittest.TestCase):
    def resolve(self,metadata=METADATA):
        calls=[]
        def request(url):
            calls.append(url)
            if urlparse(url).path.endswith('/aggregate'):return deepcopy(AGGREGATE)
            self.assertEqual('/chapter',urlparse(url).path)
            self.assertEqual({'ids[]':[CID],'limit':['100']},parse_qs(urlparse(url).query))
            if isinstance(metadata,Exception):raise metadata
            return deepcopy(metadata)
        return MangaDexStructureResolver(request_json=request).lookup(EVIDENCE),calls

    def test_bounded_metadata_type_provenance_and_no_acquisition_endpoint(self):
        result,calls=self.resolve()
        self.assertEqual(2,len(calls));self.assertEqual('valid',result['status'])
        row=result['special_records'][0]
        self.assertEqual(('2.5','special','1',CID,'pt-br'),tuple(row[k] for k in ('key','kind','volume','source_record_id','language')))
        self.assertFalse(any('/feed' in u or 'at-home' in u for u in calls))

    def test_metadata_failure_preserves_explicit_volume_structure(self):
        result,_=self.resolve(RuntimeError('offline'))
        self.assertEqual(('valid',{'2.5':'1'},[], 'transient_failure'),
            (result['status'],result['mappings'],result['special_records'],result['special_metadata_status']))

    def test_metadata_cancellation_is_not_swallowed(self):
        with self.assertRaises(CancelledError):self.resolve(CancelledError())

    def test_wrong_parent_label_volume_and_incidental_title_rejected(self):
        for field,value in (('chapter','2.1'),('volume','2'),('title','Special delivery')):
            bad=deepcopy(METADATA);bad['data'][0]['attributes'][field]=value
            self.assertEqual([],self.resolve(bad)[0]['special_records'])
        bad=deepcopy(METADATA);bad['data'][0]['relationships'][0]['id']=CID
        self.assertEqual([],self.resolve(bad)[0]['special_records'])

    def test_old_untyped_cache_refreshes_and_typed_cache_reuses(self):
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            cache=SearchMetadataCache(Path(tmp)/'cache.sqlite3')
            calls=[]
            def request(url):calls.append(url);return deepcopy(AGGREGATE if urlparse(url).path.endswith('/aggregate') else METADATA)
            resolver=MangaDexStructureResolver(cache,request)
            first=resolver.lookup(EVIDENCE);self.assertEqual(2,len(calls))
            second=resolver.lookup(EVIDENCE);self.assertEqual('hit',second['cache_state']);self.assertEqual(2,len(calls))
            for key in ('special_metadata_contract','special_metadata_status'):first.pop(key)
            import hashlib
            key='mangadex-structure-v1:'+hashlib.sha256(b'fixture:work|standard').hexdigest()
            cache.put_reference_structure(key,first)
            self.assertEqual('refreshed',resolver.lookup(EVIDENCE)['cache_state']);self.assertEqual(4,len(calls))
            cache.close()

if __name__=='__main__':unittest.main()
