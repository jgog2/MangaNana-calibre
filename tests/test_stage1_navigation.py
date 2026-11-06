"""Stage-1 navigation, conservative prepared reuse and native catalog handoff."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from dataclasses import replace
import copy,pickle,tempfile,unittest
from calibre_plugins.manganana.app.workflow_state import HighPriestessState
from calibre_plugins.manganana.publication.publication_preparation import PublicationPreparationCache,PreparedPublication
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.metadata.references.mangadex_artwork_reference import MangaDexArtworkResolver
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
from tests.test_patch1d_artwork import E,FIX_ART,MID,structure

class NavigationTests(unittest.TestCase):
    def test_import_roundtrip_preserves_executed_discovery_but_invalidates_selection(self):
        state=HighPriestessState(mode='volume',pending_query_text='Berserk')
        generation=state.execute_search(('mangadex','mangapill'))
        state.settle_provider(generation,'mangadex','success');state.settle_provider(generation,'mangapill','cancelled')
        rows=({'source_id':'mangadex','id':'exact'},)
        state.publish_search_results(generation,rows);state.select_provider(rows[0])
        for mode in ('import','chapter','import','volume'):
            state.change_mode(mode)
            self.assertEqual('Berserk',state.executed_query);self.assertEqual(rows,state.visible_provider_results)
            self.assertIsNone(state.selected_provider_record)
        self.assertFalse(state.publish_search_results(generation,({'id':'stale'},)))
    def test_import_settles_partial_search_without_erasing_arrived_rows(self):
        state=HighPriestessState(mode='chapter',executed_query='Work',provider_search_states={'mangadex':'success','mangapill':'searching'},visible_provider_results=({'id':'kept'},))
        state.change_mode('import');self.assertTrue(state.provider_barrier_complete)
        self.assertEqual('cancelled',state.provider_search_states['mangapill']);self.assertEqual('kept',state.visible_provider_results[0]['id'])
    def test_unified_shader_retains_provider_identity(self):
        from calibre_plugins.manganana.presentation.choose_manga_background import HeroSurface,NO_SELECTION_SHADER
        seen=[];host=SimpleNamespace(set_shader=seen.append)
        for source in ('mangadex','mangapill','weebcentral','mangak','atsu',None):
            HeroSurface.set_provider(host,source);self.assertEqual(source,host.provider_id)
        self.assertEqual([NO_SELECTION_SHADER]*6,seen)

class PreparationMemoTests(unittest.TestCase):
    def setUp(self):
        self.now=1.;self.cache=PublicationPreparationCache(clock=lambda:self.now)
        self.result=PreparedPublication('input',pickle.dumps([{'id':'original'}]))
        self.fn=Mock(return_value=self.result)
        self.p=patch('calibre_plugins.manganana.publication.publication_preparation.prepare_publication',self.fn);self.p.start();self.addCleanup(self.p.stop)
    def test_equal_inputs_reuse_immutable_payload_with_independent_materialization(self):
        a=self.cache.prepare({'source':'a'},{'wikipedia':{'status':'valid'}})
        b=self.cache.prepare({'source':'a'},{'wikipedia':{'status':'valid'}})
        a.materialize()[0]['id']='changed';self.assertEqual('original',b.materialize()[0]['id'])
        self.assertEqual(1,self.fn.call_count);self.assertEqual(1,self.cache.hits)
    def test_every_identity_or_evidence_change_recomputes(self):
        base=dict(source='a',edition='original',language='en',chapters=[{'id':'exact','chapter':'1'}],mode='volume',bridge='one')
        self.cache.prepare(base,{'status':'valid'})
        for key,value in (('source','b'),('edition','color'),('language','fr'),('chapters',[{'id':'other','chapter':'1'}]),('mode','chapter'),('bridge','two')):
            self.cache.prepare(dict(base,**{key:value}),{'status':'valid'})
        self.cache.prepare(base,{'status':'unavailable'})
        self.assertEqual(8,self.fn.call_count)
    def test_expiry_clock_reversal_and_cancel_do_not_promote(self):
        self.cache.prepare({},{});self.now=302.;self.cache.prepare({},{});self.now=1.;self.cache.prepare({},{})
        self.assertEqual(3,self.fn.call_count)
        with self.assertRaises(InterruptedError):self.cache.prepare({}, {},lambda:True)
        self.assertEqual(3,self.fn.call_count)
    def test_mixed_native_cover_keys_are_stable_and_do_not_conflate_types(self):
        from calibre_plugins.manganana.publication.publication_preparation import presentation_identity
        a={'covers':{None:'series',1.0:'volume'}}
        self.assertEqual(presentation_identity(a),presentation_identity({'covers':{1.0:'volume',None:'series'}}))
        self.assertNotEqual(presentation_identity(a),presentation_identity({'covers':{'None':'series','1.0':'volume'}}))
        self.cache.prepare(a,{'acquisition':a});self.cache.prepare(a,{'acquisition':a})
        self.assertEqual(1,self.fn.call_count)
    def test_budget_and_failed_evidence_are_not_retained(self):
        small=PublicationPreparationCache(max_bytes=128)
        small.prepare({},{});small.prepare({},{});self.assertEqual(0,len(small.values))
        self.cache.prepare({}, {'errors':{'wikipedia':'temporary'}});self.cache.prepare({}, {'errors':{'wikipedia':'temporary'}})
        self.assertEqual(0,len(self.cache.values))

class NativeCatalogTests(unittest.TestCase):
    def packet(self):
        rows=[r for r in FIX_ART['data']if {v.get('id')for v in r.get('relationships')or()if v.get('type')=='manga'}=={MID}]
        return {'contract':'mangadex-cover-response-v1','source':'mangadex','manga_id':MID,'complete':True,'records':copy.deepcopy(rows)}
    def test_adapter_exports_bounded_complete_catalog_without_changing_cover_mapping(self):
        rows=self.packet()['records'];source=MangaDexSource(api_json=lambda *a,**kw:dict(result='ok',data=rows,total=len(rows)))
        covers=source.get_volume_covers("https://mangadex.org/title/"+MID);self.assertTrue(covers)
        self.assertEqual(rows,source.publication_artwork_catalog['records'])
    def test_cover_pagination_rejects_oversized_or_repeated_pages(self):
        row=self.packet()['records'][0]
        source=MangaDexSource(api_json=lambda *a,**kw:dict(result='ok',data=[row]*101,total=202))
        with self.assertRaisesRegex(ValueError,'cover page'):source.get_volume_covers('https://mangadex.org/title/'+MID)
        self.assertIsNone(source.publication_artwork_catalog)
    def test_native_catalog_qualifies_and_then_serves_another_provider_from_shared_reference_cache(self):
        with tempfile.TemporaryDirectory()as temp:
            cache=SearchMetadataCache(Path(temp)/'refs.sqlite3');request=Mock(side_effect=AssertionError('No redundant cover HTTP'))
            resolver=MangaDexArtworkResolver(cache,request);identity=dict(structure(),identity_edition='original')
            first=resolver.lookup(E,identity,catalog=self.packet());self.assertEqual('acquisition_catalog',first['cache_state'])
            second=MangaDexArtworkResolver(cache,request).lookup(dict(E,requested_language='fr'),identity)
            self.assertEqual(first['covers'],second['covers']);self.assertEqual('hit',second['cache_state']);request.assert_not_called();cache.close()
    def test_catalog_does_not_override_identity_or_edition(self):
        request=Mock();resolver=MangaDexArtworkResolver(request_json=request)
        self.assertEqual('unavailable_identity',resolver.lookup(dict(E,identity_confidence='low'),structure(),catalog=self.packet())['status'])
        self.assertEqual('incompatible_edition',resolver.lookup(E,dict(structure(),identity_edition='official_color'),catalog=self.packet())['status']);request.assert_not_called()
    def test_wrong_manga_partial_or_duplicate_catalog_uses_normal_reference_path(self):
        identity=dict(structure(),identity_edition='original')
        for change in ({'manga_id':'wrong'},{'complete':False},{'records':self.packet()['records']*2}):
            request=Mock(return_value=FIX_ART)
            result=MangaDexArtworkResolver(request_json=request).lookup(E,identity,catalog=dict(self.packet(),**change))
            self.assertEqual('valid',result['status']);request.assert_called()
