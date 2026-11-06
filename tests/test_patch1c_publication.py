"""Canonical evidence order, exact BOOKWALKER part notation, and callback ownership."""
import ast
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import unquote

from calibre_plugins.manganana.metadata.reference_integration import canonical_family_publication_context, ReferenceMetadataService
from calibre_plugins.manganana.metadata.references.bookwalker_reference import BookwalkerPublicationAdapter, _search_terms
from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
from tests.test_reference_metadata_prototype import bookwalker_card_match

TITLE="JoJo's Bizarre Adventure Part 8: JoJolion"
NATIVE='ジョジョの奇妙な冒険 Part8 ジョジョリオン'
CATALOG='ジョジョの奇妙な冒険 第8部 ジョジョリオン'


def family(source):
    return {'source_id':source,'id':'provider-'+source,'title':'JoJolion',
            'author':'Hirohiko Araki','canonical_work_id':'kitsu:18812','canonical_title':TITLE,
            'canonical_aliases':[NATIVE,'JoJo no Kimyou na Bouken Part 8: JoJolion','Jojorion'],
            'canonical_creators':['Hirohiko Araki'],'canonical_creator_aliases':['Araki Hirohiko'],
            '_canonical_identity_confidence':'high','edition':'original','medium':'Comic',
            'alternate_titles':['noisy provider alias '+source]}


def bookwalker_fixture():
    """Synthetic full 27-volume catalog; exact live-observed title/seed URL."""
    ids={n:f'{n:08x}-0000-0000-0000-{n:012x}' for n in range(1,28)}
    ids[1]='e73c05f1-dd5c-46c1-8569-0c0002db3870'
    def card(n):
        return (f'<div class="m-book-item "><a href="https://bookwalker.jp/de{ids[n]}/" '
                f'class="m-book-item__title" title="{CATALOG} {n}"></a>'
                f'<img data-original="https://rimg.bookwalker.jp/{n}/thumb.jpg">'
                '<span class="a-tag-category">マンガ</span></div>')
    search=card(1)
    product=f'<link rel="canonical" href="https://bookwalker.jp/de{ids[1]}/"><title>{CATALOG} 1</title><a href="/series/13018/list/">series</a>'
    catalog=''.join(card(n) for n in range(1,28))+'<p>1～27件目/全27件</p>'
    calls=[]
    def request(url):
        calls.append(url)
        if '/search/' in url:return search if CATALOG in unquote(url) else ''
        if '/series/' in url:return catalog
        return product
    return BookwalkerPublicationAdapter(request),calls


class EmptyWiki:
    def match_publication(self,e):return PublicationMatch('wikipedia','','','no_match','fixture')


class EvidenceTests(unittest.TestCase):
    def test_provider_order_and_click_order_freeze_identical_snapshot(self):
        a,b=family('mangak'),family('atsu');b['canonical_aliases'].reverse()
        contexts=[canonical_family_publication_context(selected,rows) for selected,rows in (
            (a,[a,b]),(b,[b,a]),(a,[b,a]),(b,[a,b]))]
        self.assertTrue(all(c.shareable for c in contexts))
        self.assertTrue(all(c==contexts[0] for c in contexts))
        for c in contexts:self.assertNotIn('noisy provider',repr(c.lookup_evidence()))
        with self.assertRaises(FrozenInstanceError):contexts[0].canonical_title='changed'

    def test_untrusted_alias_media_creator_and_identity_records_excluded(self):
        selected=family('mangak');bad=[]
        for changes in ({'canonical_work_id':'other'},{'medium':'Novel'},
                        {'author':'Someone Else'},{'_canonical_identity_confidence':'low'},
                        {'edition':'official_color'}):
            bad.append(dict(family('atsu'),canonical_aliases=['Poison alias'],**changes))
        context=canonical_family_publication_context(selected,bad)
        self.assertTrue(context.shareable);self.assertNotIn('Poison',repr(context))

    def test_japanese_creator_script_is_neutral(self):
        a=family('mangak');a['author']='荒木飛呂彦'
        self.assertTrue(canonical_family_publication_context(a).shareable)

    def test_selected_creator_contradiction_cannot_borrow_peer_identity(self):
        a=family('mangak');a['author']='Someone Else'
        self.assertFalse(canonical_family_publication_context(a,[family('atsu')]).shareable)

    def test_equivalent_creator_spellings_deduplicate_by_person_identity(self):
        a,b=family('mangak'),family('atsu');b['canonical_creators']=['Araki Hirohiko']
        first=canonical_family_publication_context(a,[a,b]);second=canonical_family_publication_context(b,[b,a])
        self.assertEqual(first,second);self.assertEqual(1,len(first.canonical_creators))

    def test_multiple_creators_display_does_not_exclude_trusted_row(self):
        a=family('mangak');a.update(canonical_creators=['Creator A','Creator B'],author='Creator A, Creator B')
        self.assertTrue(canonical_family_publication_context(a).shareable)

    def test_direct_link_high_confidence_standalone_and_low_fail_closed(self):
        a=family('mangak')
        self.assertTrue(canonical_family_publication_context(a).shareable)
        a['_canonical_identity_confidence']='low'
        self.assertFalse(canonical_family_publication_context(a).shareable)

    def test_trusted_mangadex_hint_is_order_independent(self):
        a=family('mangak');md=family('mangadex');md['id']='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        c=canonical_family_publication_context(a,[md])
        self.assertEqual((md['id'],),c.lookup_evidence()['mangadex_title_ids'])

    def test_explicit_part_localization_preserves_full_title_and_number(self):
        e=canonical_family_publication_context(family('mangak')).lookup_evidence()
        self.assertIn(CATALOG,_search_terms(e))
        self.assertNotIn('ジョジョリオン',_search_terms(e))
        self.assertEqual('confident',bookwalker_card_match(CATALOG+' 1',e).confidence)
        self.assertEqual('ambiguous',bookwalker_card_match(CATALOG.replace('第8部','第7部')+' 1',e).confidence)
        self.assertEqual('ambiguous',bookwalker_card_match('別冊 '+CATALOG+' 1',e).confidence)
        self.assertEqual('ambiguous',bookwalker_card_match(CATALOG+' カラー版 1',e).confidence)

    def test_mangak_and_atsu_cold_catalogs_both_resolve_27(self):
        a,b=family('mangak'),family('atsu');seen=[]
        for selected,rows in ((a,[a,b]),(b,[b,a])):
            e=canonical_family_publication_context(selected,rows).lookup_evidence();seen.append(e)
            adapter,calls=bookwalker_fixture()
            result=ReferenceMetadataService(None,EmptyWiki(),adapter).lookup('work',e)['bookwalker']
            self.assertEqual(('series/13018',27),(result['match']['publication_id'],len(result['covers'])))
            self.assertTrue(any(CATALOG in unquote(url) for url in calls))
        self.assertEqual(seen[0],seen[1])

    def test_warm_cache_does_not_change_evidence_and_no_match_not_cached(self):
        a,b=family('mangak'),family('atsu')
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'reference.sqlite3')
            e1=canonical_family_publication_context(a,[a,b]).lookup_evidence()
            empty=ReferenceMetadataService(cache,EmptyWiki(),EmptyWiki()).lookup('work',e1)
            adapter,calls=bookwalker_fixture()
            first=ReferenceMetadataService(cache,EmptyWiki(),adapter).lookup('work',e1)
            e2=canonical_family_publication_context(b,[b,a]).lookup_evidence()
            adapter2,calls2=bookwalker_fixture()
            second=ReferenceMetadataService(cache,EmptyWiki(),adapter2).lookup('work',e2)
            self.assertEqual(e1,e2);self.assertEqual(27,len(first['bookwalker']['covers']))
            self.assertEqual(('hit',27,[]),(second['bookwalker']['cache_state'],len(second['bookwalker']['covers']),calls2))
            cache.close()

    def test_stale_reference_callback_rejected_before_any_mutation(self):
        root=Path(__file__).parents[1];tree=ast.parse((root/'app/main.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MangaNanaDialog')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_on_reference_lookup_ready')
        scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'reference-callback','exec'),scope)
        target=SimpleNamespace(_closing=False,_reference_request_id=8,workflow_state=SimpleNamespace(selected_record_load_generation=3),loaded_metadata={'title':'Current'})
        before=repr(target.__dict__)
        for payload in ({'request_id':7,'generation':3},{'request_id':8,'generation':2}):
            scope['_on_reference_lookup_ready'](target,payload)
            self.assertEqual(before,repr(target.__dict__))


if __name__=='__main__':unittest.main()
