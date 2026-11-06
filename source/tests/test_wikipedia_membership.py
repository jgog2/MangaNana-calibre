"""Bounded explicit labeled memberships, not prose or inferred numbering."""
from dataclasses import asdict
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter
from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService, _usable_wikipedia_cache
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache

TITLE='List of Synthetic work chapters'
TEXT=(Path(__file__).parent/'fixtures/wikipedia_labeled_membership.wiki').read_text(encoding='utf-8')


def graphic(value, volume='6', field='ChapterList'):
    return '{{Graphic novel list|VolumeNumber='+volume+'|OriginalRelDate=January 1, 2024|'+field+'='+value+'}}'


def parsed(text=TEXT):
    def request(params):
        if params['action']=='query':return {'query':{'search':[dict(pageid=10,title=TITLE)]}}
        return {'parse':dict(title=TITLE,pageid=10,revid=20,wikitext={'*':text})}
    adapter=WikipediaPublicationAdapter(request)
    match=adapter.match_publication(dict(title='Synthetic work',edition='original'))
    return adapter,match,adapter.resolve_publication(match)


class WikipediaMembership(unittest.TestCase):
    def test_generic_early_middle_late_boundaries_and_consecutive_rows(self):
        _,_,result=parsed()
        mapping={r.number:r.volume for r in result['chapters'] if r.kind=='chapter'}
        self.assertEqual('valid_with_data',result['status'])
        self.assertEqual(127,len(mapping))
        for key,volume in (('1','1'),('5','1'),('6','2'),('31','6'),('37','6'),('38','7'),
                           ('108','15'),('109','16'),('118','16'),('119','17'),('127','17')):
            self.assertEqual(volume,mapping[key])

    def test_short_and_extra_namespaces_preserve_labels_numbers_and_provenance(self):
        _,_,result=parsed();short={r.number:r for r in result['chapters'] if r.kind=='special'}
        self.assertEqual('6',short['Short Mission 4'].volume)
        self.assertEqual('2',short['Extra Mission 1'].volume)
        self.assertEqual({'Short Mission 15','Short Mission 17','Short Mission 18'},
            {r.number for r in short.values() if r.volume=='17'})
        self.assertTrue(all(r.source_record_id and r.source_page==TITLE for r in short.values()))
        self.assertFalse(any(r.number=='4' and r.kind=='special' for r in short.values()))

    def test_integer_uncollected_tail_is_exact_and_volume_free(self):
        _,_,result=parsed()
        tail=[r for r in result['chapters'] if r.kind=='uncollected']
        self.assertEqual([str(n) for n in range(128,135)],[r.number for r in tail])
        self.assertTrue(all(not r.volume for r in tail))
        short=next(r for r in result['chapters'] if r.number=='Short Mission 19')
        self.assertEqual(('special',''),(short.kind,short.volume))

    def test_main_labels_are_bounded_publication_terms(self):
        for label in ('Chapter','Episode','Round','Mission'):
            _,_,result=parsed(graphic('*'+label+': 31-33'))
            self.assertEqual(['31','32','33'],[r.number for r in result['chapters']])

    def test_prose_and_unsupported_labels_do_not_emit_main(self):
        for text in ('Mission: 31-37\n'+graphic('',field='ChapterList'),
                     graphic('The characters discuss Mission 31-37.'),graphic('*Event: 31-37'),
                     graphic('*Mission: 31-37',field='Summary')):
            _,_,result=parsed(text)
            self.assertFalse(any(r.kind=='chapter' for r in result['chapters']))

    def test_reversed_malformed_and_oversized_ranges_remain_unresolved(self):
        for expr in ('37-31','31--37','31-','31, unknown','1-100000'):
            _,_,result=parsed(graphic('*Mission: '+expr))
            self.assertFalse(any(r.kind=='chapter' for r in result['chapters']))

    def test_exact_decimals_are_retained_without_float_arithmetic(self):
        _,_,result=parsed(graphic('*Mission: 58.1, 58.2, 0'))
        self.assertEqual(['58.1','58.2','0'],[r.number for r in result['chapters']])

    def test_mixed_decimal_range_is_preserved_not_expanded(self):
        _,_,result=parsed(graphic('*Mission: 128-140.1'))
        self.assertEqual(1,len(result['chapters']))
        row=result['chapters'][0]
        self.assertEqual('128-140.1',row.number)
        self.assertNotEqual('chapter',row.kind)
        self.assertTrue(row.source_record_id)

    def test_mixed_decimal_uncollected_range_preserves_evidence_without_future_membership(self):
        _,_,result=parsed(TEXT.replace('128–134','128–140.1'))
        row=next(r for r in result['chapters'] if r.number=='128–140.1')
        self.assertEqual(('uncollected_range',''),(row.kind,row.volume))
        self.assertFalse(any(r.number.startswith('140.0') for r in result['chapters']))

    def test_missing_volume_does_not_create_membership(self):
        _,_,result=parsed(graphic('*Mission: 31-37',volume=''))
        self.assertFalse(result['chapters'])

    def test_main_and_short_local_number_do_not_merge(self):
        _,_,result=parsed(graphic('*Mission: 4\n*Short Mission: 4'))
        self.assertEqual([('4','chapter'),('Short Mission 4','special')],[(r.number,r.kind) for r in result['chapters']])

    def test_duplicate_equivalent_evidence_does_not_invent_conflict(self):
        _,_,result=parsed(graphic('*Mission: 31-33\n*Mission: 31-33'))
        records={r.number:r.volume for r in result['chapters']}
        self.assertEqual({'31':'6','32':'6','33':'6'},records)

    def test_overlapping_incompatible_volumes_reach_existing_ambiguity(self):
        _,match,result=parsed(graphic('*Mission: 31-33','6')+graphic('*Mission: 33-35','7'))
        wiki=dict(status=result['status'],match=asdict(match),chapters=[asdict(r) for r in result['chapters']])
        builder=PublicationManifestBuilder(dict(canonical_identity='fixture',title='Synthetic work'),'original')
        manifest=builder.apply_wikipedia(wiki).build()
        self.assertIn('33',manifest.ambiguous_chapter_keys)

    def test_ambiguous_same_work_subsections_do_not_select_first(self):
        text='== Synthetic work ==\n'+graphic('*Mission: 31-33')+'\n== Synthetic work ==\n'+graphic('*Mission: 41-43')
        _,_,result=parsed(text)
        self.assertFalse(result['chapters'])

    def test_uncollected_exact_evidence_overrides_planned_row_without_guessing(self):
        text=graphic('*Mission: 128-134','18')+'\n== Chapters not yet in tankōbon format ==\n*Mission: 128-134'
        _,_,result=parsed(text)
        self.assertEqual(['uncollected']*7,[r.kind for r in result['chapters']])
        self.assertTrue(all(not r.volume for r in result['chapters']))

    def test_parser_version_invalidates_old_nonempty_and_empty_cache(self):
        adapter,_,result=parsed()
        for chapters in ([],[asdict(result['chapters'][0])]):
            old=dict(cache_contract='wikipedia-structure-v3-collection',parser_pattern=adapter.pattern_id,
                parser_version='6',status='valid_with_data' if chapters else 'supported_empty',chapters=chapters)
            self.assertFalse(_usable_wikipedia_cache(old,adapter))
        self.assertNotEqual('6',adapter.parser_version)

    def test_old_segment_cannot_hide_new_memberships_and_current_segment_reuses_provenance(self):
        adapter,match,_=parsed()
        writes={}; requested=[]
        def old_segment(key):
            requested.append(key)
            return dict(cache_contract='wikipedia-segment-v1',page_id='10',revision_id='20',
                parser_pattern=adapter.pattern_id,parser_version='6',
                chapters=[dict(number='999',volume='1')],volumes=[])
        first=adapter.resolve_publication(match,old_segment,writes.__setitem__)
        self.assertNotIn('999',[r.number for r in first['chapters']])
        self.assertTrue(all(key.endswith(':'+adapter.parser_version) for key in requested))
        second=adapter.resolve_publication(match,writes.get)
        self.assertEqual(first['chapters'],second['chapters'])
        self.assertEqual(1,adapter.segment_cache_hits)

    def test_old_outer_cache_refreshes_then_current_cache_hits(self):
        class NoBooks:
            def match_publication(self,evidence):
                return PublicationMatch('bookwalker','','','no_match','offline')
        evidence=dict(title='Synthetic work',edition='original')
        for old_chapters in ([],[dict(number='999',volume='1')]):
            adapter,_,_=parsed()
            with tempfile.TemporaryDirectory() as folder, closing(SearchMetadataCache(Path(folder)/'cache.sqlite3')) as cache:
                cache.put_reference_structure('work:fixture',dict(resolved_key='old'))
                cache.put_reference_structure('old',dict(cache_contract='wikipedia-structure-v3-collection',
                    parser_pattern=adapter.pattern_id,parser_version='6',
                    status='valid_with_data' if old_chapters else 'supported_empty',chapters=old_chapters))
                service=ReferenceMetadataService(cache,adapter,NoBooks())
                first=service.lookup('fixture',evidence)['wikipedia']
                second=service.lookup('fixture',evidence)['wikipedia']
                self.assertEqual((adapter.parser_version,'refreshed_after_invalidation','hit'),
                    (first['parser_version'],first['cache_state'],second['cache_state']))
                self.assertEqual(127,sum(r['kind']=='chapter' for r in first['chapters']))
                self.assertNotIn('999',[r['number'] for r in first['chapters']])
                self.assertEqual(json.loads(json.dumps(first['chapters'])),second['chapters'])

    def test_main_and_short_ranges_share_local_numbers_without_collision(self):
        _,_,result=parsed(graphic('*Mission: 1–2\n*Short Mission: 1–2'))
        self.assertEqual([('1','chapter'),('2','chapter'),('Short Mission 1','special'),
                          ('Short Mission 2','special')],[(r.number,r.kind) for r in result['chapters']])

    def test_source_label_case_is_preserved_without_changing_namespace(self):
        _,_,result=parsed(graphic('*mission: 4\n*short mission: 4'))
        self.assertEqual([('4','chapter'),('short mission 4','special')],[(r.number,r.kind) for r in result['chapters']])

    def test_total_list_bound_and_exact_source_decimal_normalization(self):
        _,_,result=parsed(graphic('*Mission: 1-200, 201, 202'))
        self.assertFalse(any(r.kind=='chapter' for r in result['chapters']))
        _,_,result=parsed(graphic('*Mission: 058.10, -1.5'))
        self.assertEqual(['58.1','-1.5'],[r.number for r in result['chapters']])


if __name__=='__main__':unittest.main()
