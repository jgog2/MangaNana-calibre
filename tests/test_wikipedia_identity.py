"""Chapter-list roles and typography must not manufacture work ambiguity."""
from copy import deepcopy
import unittest

from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter
from calibre_plugins.manganana.publication.publication_freshness import trusted_wikipedia_records
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService

TEXT='''{{Graphic novel list|VolumeNumber=1|ChapterListCol1=
* 58.1. First
* 58.2. Second
}}'''


def adapter(rows, text=TEXT):
    calls=[]
    def request(params):
        calls.append(dict(params))
        if params['action']=='query': return {'query':{'search':deepcopy(rows)}}
        return {'parse':{'title':params['page'],'pageid':2,'revid':12,'wikitext':{'*':text if params['page'].startswith('List of ') else 'Series introduction'}}}
    return WikipediaPublicationAdapter(request),calls


class WikipediaIdentity(unittest.TestCase):
    def test_list_and_main_alias_are_one_work(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta'),dict(pageid=2,title='List of Alpha x Beta chapters')])
        match=a.match_publication(dict(title='Alpha x Beta',aliases=['List of Alpha x Beta chapters'],edition='original'))
        self.assertEqual('confident',match.confidence)
        self.assertEqual('List of Alpha x Beta chapters',match.title)

    def test_list_is_found_without_a_list_alias(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta'),dict(pageid=2,title='List of Alpha x Beta chapters')])
        self.assertEqual('List of Alpha x Beta chapters',a.match_publication(dict(title='Alpha x Beta',edition='original')).title)

    def test_typographic_cross_and_case_whitespace_are_comparison_only(self):
        title='List of Alpha × Beta chapters'
        a,_=adapter([dict(pageid=2,title=title)])
        match=a.match_publication(dict(title='ALPHA x BETA',edition='original'))
        self.assertEqual(('confident',title),(match.confidence,match.title))
        self.assertEqual('2',match.publication_id)

    def test_unspaced_cross_and_unicode_spaces_are_supported(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha×Beta chapters')])
        self.assertEqual('confident',a.match_publication(dict(title='Alpha\u00a0x\u00a0Beta',edition='original')).confidence)

    def test_other_exact_work_alias_remains_ambiguous(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters'),dict(pageid=3,title='Other work')])
        self.assertEqual('ambiguous',a.match_publication(dict(title='Alpha x Beta',aliases=['Other work'],edition='original')).confidence)

    def test_two_distinct_eligible_list_pages_remain_ambiguous(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters'),dict(pageid=3,title='List of Alpha × Beta chapters')])
        self.assertEqual('ambiguous',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_repeated_search_result_same_page_id_is_not_a_second_work(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters')]*2)
        self.assertEqual('confident',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_spinoff_prefix_is_not_exact_identity(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta Extra chapters')])
        self.assertNotEqual('confident',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_edition_suffix_is_not_dropped(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters (omnibus edition)')])
        self.assertNotEqual('confident',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_wrong_edition_alias_does_not_promote_list(self):
        title='List of Alpha x Beta omnibus chapters'
        a,_=adapter([dict(pageid=2,title=title)])
        self.assertNotEqual('confident',a.match_publication(dict(title='Alpha x Beta',aliases=[title],edition='original')).confidence)

    def test_namespace_is_not_a_publication_page(self):
        a,_=adapter([dict(pageid=2,title='Category:List of Alpha x Beta chapters')])
        self.assertNotEqual('confident',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_list_match_reaches_trusted_records_and_preserves_fraction_identity(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta'),dict(pageid=2,title='List of Alpha × Beta chapters')])
        class Empty:
            def match_publication(self,evidence):
                from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
                return PublicationMatch('bookwalker','','','no_match','offline')
        evidence=dict(title='Alpha x Beta',canonical_title='Alpha x Beta',canonical_work_id='fixture:alpha',
            identity_confidence='high',edition='original',requested_language='en',media_type='manga')
        bundle=ReferenceMetadataService(None,a,Empty()).lookup('fixture:alpha',evidence)
        identity=dict(trusted=True,canonical_work_id='fixture:alpha',edition='original',language='en')
        context=dict(shareable=True,canonical_work_id='fixture:alpha',canonical_title='Alpha x Beta')
        rows=trusted_wikipedia_records(bundle,identity,context)
        self.assertEqual(['58.1','58.2'],[r['key'] for r in rows])
        self.assertEqual('List of Alpha × Beta chapters',bundle['wikipedia']['match']['title'])
        self.assertTrue(all(r['source_page']=='List of Alpha × Beta chapters' for r in rows))

    def test_main_only_existing_path_still_works(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta')])
        self.assertEqual('Alpha x Beta',a.match_publication(dict(title='Alpha x Beta',edition='original')).title)

    def test_typography_is_used_for_related_list_and_subsection_scope(self):
        a,_=adapter([])
        self.assertTrue(a._is_related_chapter_page('Alpha x Beta','List of Alpha × Beta chapters'))
        text='== Alpha × Beta ==\nMain\n== Alpha x Beta Extra ==\nOther'
        self.assertEqual('\nMain\n',a._main_series_section(text,'List of Alpha x Beta chapters'))

    def test_corresponding_manga_article_alone_does_not_defeat_list(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta (manga)'),dict(pageid=2,title='List of Alpha x Beta chapters')])
        self.assertEqual('List of Alpha x Beta chapters',a.match_publication(dict(title='Alpha x Beta',edition='original')).title)

    def test_homonym_article_and_manga_without_corroboration_still_ambiguous(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta'),dict(pageid=3,title='Alpha x Beta (manga)'),
                     dict(pageid=2,title='List of Alpha x Beta chapters')])
        self.assertEqual('ambiguous',a.match_publication(dict(title='Alpha x Beta',edition='original')).confidence)

    def test_homonym_manga_corroboration_can_resolve_list(self):
        a,_=adapter([dict(pageid=1,title='Alpha x Beta'),dict(pageid=3,title='Alpha x Beta (manga)',snippet='Written by Fixture Author'),
                     dict(pageid=2,title='List of Alpha x Beta chapters')])
        self.assertEqual('List of Alpha x Beta chapters',a.match_publication(dict(title='Alpha x Beta',author='Fixture Author',edition='original')).title)

    def test_structure_fallback_prefers_exact_list_over_same_work_segments(self):
        from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
        a,_=adapter([dict(pageid=2,title='List of Alpha × Beta chapters'),
                     dict(pageid=3,title='List of Alpha x Beta chapters (1–10)')])
        match=PublicationMatch('wikipedia','1','Alpha x Beta','confident','fixture',edition='original')
        self.assertEqual('List of Alpha × Beta chapters',a.get_structure_page(match))

    def test_structure_fallback_distinct_exact_page_variants_remain_ambiguous(self):
        from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
        a,_=adapter([dict(pageid=2,title='List of Alpha × Beta chapters'),dict(pageid=3,title='List of Alpha x Beta chapters')])
        match=PublicationMatch('wikipedia','1','Alpha x Beta','confident','fixture',edition='original')
        self.assertEqual('',a.get_structure_page(match))

    def test_redirect_to_another_work_or_edition_does_not_resolve(self):
        for target in ('List of Other work chapters','List of Alpha x Beta omnibus chapters'):
            a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters')])
            match=a.match_publication(dict(title='Alpha x Beta',edition='original'))
            a._request_json=lambda params:dict(parse=dict(title=target,pageid=3,revid=13,wikitext={'*':TEXT}))
            self.assertEqual('ambiguous_identity',a.resolve_publication(match)['status'])

    def test_two_plausible_edition_titles_do_not_collapse(self):
        a,_=adapter([dict(pageid=2,title='List of Alpha x Beta chapters'),
                     dict(pageid=3,title='List of Alpha x Beta Deluxe Edition chapters')])
        match=a.match_publication(dict(title='Alpha x Beta',aliases=['Alpha x Beta Deluxe Edition'],edition='original'))
        self.assertEqual('ambiguous',match.confidence)


if __name__=='__main__': unittest.main()
