import unittest
from itertools import permutations

from canonical_identity import CanonicalGroup, edition_classification, edition_display_label, edition_identity, group_canonical_results, merge_calibre_tags, normalize_identity_text
from enrichment_matching import (
    canonical_creator_value, consensus_rating, enrich_content_results, match_external_identity,
    normalized_popularity, propagate_trusted_family_work_facts,
    resolve_canonical_work_facts, trusted_alias_for_query,
)
from enrichment_model import (
    EditionClass, ExternalMangaCandidate, IdentityConfidence,
    PopularitySignal, RatingSignal,
)
from search_ranking import rank_canonical_results, rank_provider_results
from reference_integration import canonical_publication_context


def external(title, service='anilist', *, aliases=(), authors=(), year=None,
             rating=8.0, samples=None, readers=1000, favourites=100,
             description='', tags=()):
    return ExternalMangaCandidate(
        service=service, external_id=service + '-1', primary_title=title,
        aliases=tuple(aliases), authors=tuple(authors), description=description,
        tags=tuple(tags), start_year=year,
        cross_ids={service + '_id': service + '-1'},
        rating=RatingSignal(rating, samples, service),
        popularity=PopularitySignal(readers, favourites, None, service),
    )


def content(title, source='mangadex', **extra):
    return {'source_id': source, 'source_name': source, 'id': source + title,
            'title': title, 'full_title': title, 'alternate_titles': [], **extra}


class EnrichmentMatchingTests(unittest.TestCase):
    @staticmethod
    def trusted_family_donor(title='Example Work'):
        return {
            'source_id':'mangadex','id':'standard','title':title,
            'canonical_work_id':'anilist:100|kitsu:200',
            'canonical_title':'Example Canonical','canonical_author':'Creator One',
            'canonical_creators':['Creator One'],
            'canonical_creator_aliases':['One Creator'],
            'canonical_creator_provenance':'trusted_external',
            'canonical_aliases':['Example Work'],
            'external_ids':{'anilist_id':'100','kitsu_id':'200'},
            'work_family_id':'trusted-family','_canonical_identity_confidence':'high',
            'edition':'original','bookwalker_covers':['standard-only'],
        }

    def test_trusted_work_facts_cross_exact_edition_siblings_without_edition_or_artwork(self):
        standard=self.trusted_family_donor()
        official={'source_id':'mangapill','id':'color',
                  'title':'Example Work Official Colored','edition':'official_color'}
        fan={'source_id':'other','id':'fan','title':'Example Work Fan Colored',
             'edition':'fan_color'}
        rows=propagate_trusted_family_work_facts((standard,official,fan))
        standard_row,official_row,fan_row=rows
        self.assertEqual(('anilist:100|kitsu:200',)*3,
                         tuple(row.get('canonical_work_id') for row in rows))
        self.assertEqual(('original','official_color','fan_color'),
                         tuple(edition_identity(row) for row in rows))
        self.assertEqual('Example Work Official Colored',official_row['title'])
        self.assertNotIn('bookwalker_covers',official_row)
        self.assertEqual(['standard-only'],standard_row['bookwalker_covers'])
        context=canonical_publication_context(official_row['canonical_work_id'],{
            'canonical_title':official_row['canonical_title'],
            'trusted_aliases':official_row['canonical_aliases'],
            'canonical_author':official_row['canonical_author'],
            'canonical_creators':official_row['canonical_creators'],
            'canonical_creator_aliases':official_row['canonical_creator_aliases'],
            'identity_confidence':official_row['_canonical_identity_confidence'],
            'edition':edition_identity(official_row),
        })
        self.assertTrue(context.shareable)
        self.assertTrue(context.reference_key.endswith('|color'))

    def test_family_work_fact_conflicts_and_nonexact_titles_fail_closed(self):
        first=self.trusted_family_donor()
        second={**self.trusted_family_donor(),'source_id':'second','id':'second',
                'canonical_work_id':'anilist:999'}
        sibling={'source_id':'mangapill','id':'color',
                 'title':'Example Work Official Colored','edition':'official_color'}
        conflicting=propagate_trusted_family_work_facts((first,second,sibling))
        self.assertNotIn('canonical_work_id',conflicting[2])

        contradicted=propagate_trusted_family_work_facts((
            first,{**sibling,'author':'Different Creator'},
        ))
        self.assertNotIn('canonical_work_id',contradicted[1])

        similar=propagate_trusted_family_work_facts((
            first,{**sibling,'title':'Example Work Side Story Official Colored'},
        ))
        self.assertNotIn('canonical_work_id',similar[1])

    @staticmethod
    def _work_fact(rows, overlays=None):
        facts=resolve_canonical_work_facts(group_canonical_results(rows),overlays)
        return next(iter(facts.values()))

    def test_work_fact_creator_precedence_and_provider_single_fallback(self):
        rows=(content('One Piece','mangadex',author='Oda Eiichiro'),
              content('One Piece','mangapill'),content('One Piece','weebcentral'))
        provider=self._work_fact(rows)
        self.assertEqual(('Oda Eiichiro','provider_consensus'),(provider.creator,provider.creator_provenance))
        overlays={(row['source_id'],row['id']):{
            'canonical_author':'Eiichiro Oda','canonical_creator_provenance':'trusted_external',
            'canonical_work_id':'anilist:21','canonical_title':'One Piece',
        } for row in rows}
        external=self._work_fact(rows,overlays)
        self.assertEqual(('Eiichiro Oda','trusted_external','anilist:21'),(
            external.creator,external.creator_provenance,external.canonical_work_id,
        ))

    def test_trusted_creator_fact_retains_only_identity_equivalent_display_aliases(self):
        rows=(content('Bleach','mangadex',author='Kubo Tite'),
              content('Bleach','mangapill'))
        overlays={(row['source_id'],row['id']):{
            'canonical_author':'Tite Kubo','canonical_creator_provenance':'trusted_external',
            'canonical_creator_aliases':('Tite Kubo','Kubo Tite','Another Creator'),
            'canonical_work_id':'anilist:30012|anilist:41330','canonical_title':'Bleach',
        } for row in rows}
        fact=self._work_fact(rows,overlays)
        self.assertEqual(('Tite Kubo','Kubo Tite'),fact.creator_aliases)

    def test_cached_creator_and_safe_provider_consensus_survive_optional_failure(self):
        rows=(content('One Piece','mangadex',author='ODA Eiichiro'),
              content('One Piece','mangapill',author='Eiichiro Oda'))
        group=CanonicalGroup('One Piece',(),rows,('mangadex','mangapill'),
                             ('MangaDex','MangaPill'),'high','independent fixture')
        consensus=next(iter(resolve_canonical_work_facts((group,)).values()))
        self.assertEqual(('Eiichiro Oda','provider_consensus'),
                         (consensus.creator,consensus.creator_provenance))
        cached={(row['source_id'],row['id']):{
            'canonical_author':'Eiichiro Oda','canonical_creator_provenance':'cached_canonical',
        } for row in rows}
        recovered=next(iter(resolve_canonical_work_facts((group,),cached).values()))
        self.assertEqual(('Eiichiro Oda','cached_canonical'),
                         (recovered.creator,recovered.creator_provenance))

    def test_conflicting_creator_evidence_fails_closed_and_ambiguous_group_is_not_consolidated(self):
        conflict=CanonicalGroup('Example',(),(
            content('Example','mangadex',author='Oda Eiichiro'),
            content('Example','mangapill',author='Bob Smith'),
        ),('mangadex','mangapill'),('MangaDex','MangaPill'),'high','fixture')
        fact=next(iter(resolve_canonical_work_facts((conflict,)).values()))
        self.assertEqual(('',True),(fact.creator,fact.creator_conflicted))
        ambiguous=CanonicalGroup('Example',(),(content('Example','mangadex',author='Oda Eiichiro'),),
                                 ('mangadex',),('MangaDex',),'single','fixture')
        self.assertEqual({},resolve_canonical_work_facts((ambiguous,)))

    def test_no_creator_evidence_remains_blank(self):
        fact=self._work_fact((content('One Piece','mangadex'),content('One Piece','mangapill')))
        self.assertEqual(('',False),(fact.creator,fact.creator_conflicted))
    def test_high_medium_and_reject_identity_states(self):
        self.assertIs(
            IdentityConfidence.HIGH,
            match_external_identity(content('Attack on Titan', year=2009), external('Attack on Titan', year=2009)).confidence,
        )
        alias_only = content('Attack on Titan', alternate_titles=['Shingeki no Kyojin'])
        self.assertIs(
            IdentityConfidence.MEDIUM,
            match_external_identity(alias_only, external('Shingeki no Kyojin')).confidence,
        )
        conflicting = content('Attack on Titan', author='Other Author')
        self.assertIs(
            IdentityConfidence.REJECT,
            match_external_identity(conflicting, external('Attack on Titan', authors=('Hajime Isayama',))).confidence,
        )
        reordered = content('Attack on Titan', author='ISAYAMA Hajime')
        self.assertIs(
            IdentityConfidence.HIGH,
            match_external_identity(reordered, external('Attack on Titan', authors=('Hajime Isayama',))).confidence,
        )

    def test_alias_only_nearby_year_does_not_promote_unrelated_work(self):
        provider=content('Hajime no Ippo',year=1989)
        unrelated=ExternalMangaCandidate(
            service='kitsu',external_id='44040',primary_title='Yami Kariudo',
            aliases=('Hajime no Ippo!',),start_year=1990,
        )
        match=match_external_identity(provider,unrelated)
        self.assertIsNot(IdentityConfidence.HIGH,match.confidence)
        self.assertIn('alias',match.reason)

    def test_canonical_title_and_work_id_are_candidate_order_independent(self):
        provider=(content('Hajime no Ippo',year=1989),)
        candidates=(
            ExternalMangaCandidate(
                service='anilist',external_id='30007',primary_title='Hajime no Ippo',
                english_title='Hajime no Ippo: Fighting Spirit!',
                authors=('George Morikawa',),start_year=1989,
            ),
            ExternalMangaCandidate(
                service='kitsu',external_id='23',primary_title='Hajime no Ippo',
                authors=('George Morikawa',),start_year=1989,
            ),
        )
        outputs=[]
        for ordered in (candidates,tuple(reversed(candidates)),(candidates[1],candidates[0])):
            row=enrich_content_results(provider,ordered)[0]
            context=canonical_publication_context(row['canonical_work_id'],{
                'canonical_title':row['canonical_title'],
                'canonical_author':row['canonical_author'],
                'canonical_creators':row['canonical_creators'],
                'canonical_creator_aliases':row['canonical_creator_aliases'],
                'provider_author':'Morikawa George','edition':'original',
                'identity_confidence':'high',
            })
            outputs.append((row['canonical_title'],row['canonical_work_id'],context.reference_key))
        self.assertEqual(1,len(set(outputs)))
        self.assertEqual(('Hajime no Ippo','anilist:30007|kitsu:23',
                          'anilist-30007|kitsu-23|hajime-no-ippo|standard'),outputs[0])

    def test_final_ippo_work_facts_are_invariant_across_all_provider_orders(self):
        cards=(
            content('Hajime no Ippo: Fighting Spirit!','mangadex'),
            content('Hajime no Ippo','mangapill'),
            content('Hajime no Ippo','weebcentral'),
        )
        for row in cards:
            row.update({
                'canonical_work_id':'anilist:30007',
                'canonical_title':row['title'],
                'canonical_author':'George Morikawa',
                'canonical_creators':('George Morikawa',),
                'canonical_creator_provenance':'trusted_external',
                '_canonical_identity_confidence':'high',
                'work_family_id':'canonical:hajime no ippo:original',
                'edition':'original',
            })
        outcomes=[]
        for ordered in permutations(cards):
            groups=group_canonical_results(ordered)
            self.assertEqual(1,len(groups))
            fact=next(iter(resolve_canonical_work_facts(groups).values()))
            context=canonical_publication_context(fact.canonical_work_id,{
                'canonical_title':fact.canonical_title,
                'canonical_author':fact.creator,
                'canonical_creators':fact.creators,
                'canonical_creator_aliases':fact.creator_aliases,
                'provider_author':'George Morikawa','edition':'original',
                'identity_confidence':'high',
            })
            outcomes.append((
                fact.canonical_title,normalize_identity_text(fact.canonical_title),
                fact.canonical_work_id,
                tuple(sorted(row['work_family_id'] for row in ordered)),
                context.reference_key.split('|')[-2],context.edition_profile,
            ))
        self.assertEqual(1,len(set(outcomes)))
        self.assertEqual(('Hajime no Ippo','hajime no ippo','anilist:30007',
                          ('canonical:hajime no ippo:original',)*3,
                          'hajime-no-ippo','standard'),outcomes[0])

    def test_final_ippo_title_is_stable_with_or_without_optional_kitsu_id(self):
        outcomes=[]
        for work_id in ('anilist:30007','anilist:30007|kitsu:23'):
            rows=[]
            for source,title in (
                    ('mangadex','Hajime no Ippo: Fighting Spirit!'),
                    ('mangapill','Hajime no Ippo'),
                    ('weebcentral','Hajime no Ippo')):
                row=content(title,source)
                row.update({
                    'canonical_work_id':work_id,'canonical_title':title,
                    'canonical_author':'George Morikawa',
                    'canonical_creators':('George Morikawa',),
                    'canonical_creator_provenance':'trusted_external',
                    '_canonical_identity_confidence':'high',
                    'work_family_id':'canonical:hajime no ippo:original',
                    'edition':'original',
                })
                rows.append(row)
            fact=next(iter(resolve_canonical_work_facts(
                group_canonical_results(tuple(reversed(rows)))
            ).values()))
            context=canonical_publication_context(fact.canonical_work_id,{
                'canonical_title':fact.canonical_title,
                'canonical_author':fact.creator,'canonical_creators':fact.creators,
                'provider_author':'George Morikawa','edition':'original',
                'identity_confidence':'high',
            })
            outcomes.append((fact.canonical_title,fact.canonical_work_id,context.reference_key))
        self.assertEqual([
            ('Hajime no Ippo','anilist:30007','anilist-30007|hajime-no-ippo|standard'),
            ('Hajime no Ippo','anilist:30007|kitsu:23',
             'anilist-30007|kitsu-23|hajime-no-ippo|standard'),
        ],outcomes)

    def test_trusted_multi_creator_components_remain_structured(self):
        row=enrich_content_results(
            (content('Berserk',year=1989),),
            (ExternalMangaCandidate(
                service='anilist',external_id='30002',primary_title='Berserk',
                authors=('Kentarou Miura','Studio Gaga'),start_year=1989,
            ),),
        )[0]
        self.assertEqual(['Kentarou Miura','Studio Gaga'],row['canonical_creators'])
        self.assertEqual('Kentarou Miura, Studio Gaga',row['canonical_author'])

    def test_work_rating_is_inherited_without_merging_editions(self):
        rows = enrich_content_results((
            content('One Punch Man', 'mangadex', year=2012),
            content('One Punch Man Official Colored', 'mangapill'),
            content('One Punch Man Fan Colored', 'weebcentral'),
        ), (external('One Punch Man', year=2012, rating=8.7),))
        self.assertEqual(3, len(rows))
        self.assertEqual(1, len({row['work_family_id'] for row in rows}))
        self.assertTrue(all(row['rating_display'] == '8.7/10' for row in rows))
        self.assertEqual(3, len(rank_canonical_results('One Punch Man', rows)))

    def test_unknown_never_displays_false_bw_and_color_marker_is_detected(self):
        self.assertIs(EditionClass.UNKNOWN, edition_classification(content('Unknown Edition')))
        self.assertEqual('', edition_display_label(content('Unknown Edition')))
        colored = content('Chainsaw Man (Color)')
        self.assertIs(EditionClass.OFFICIAL_COLOR, edition_classification(colored))
        self.assertEqual('COLOR', edition_display_label(colored))

    def test_explicit_color_wording_uses_one_shared_classifier(self):
        for title in ('Death Note (Color)', 'Death Note (Colored)', 'Death Note Full Color',
                      'Death Note Digital Colored', 'Death Note Officially Coloured'):
            self.assertIs(EditionClass.OFFICIAL_COLOR, edition_classification(content(title)))
            self.assertEqual('COLOR', edition_display_label(content(title)))

    def test_trusted_work_metadata_is_shared_only_by_independently_matched_editions(self):
        candidate=external('One Punch Man', year=2012, authors=('ONE',),
                           description='A hero for fun.', tags=('Action', 'Comedy', 'action'))
        rows=enrich_content_results((
            content('One Punch Man', year=2012),
            content('One Punch Man Official Colored', year=2012),
            content('One Punch Manga'),
        ),(candidate,))
        self.assertEqual('A hero for fun.',rows[0]['work_description'])
        self.assertEqual(['Action','Comedy'],rows[0]['work_tags'])
        self.assertEqual(rows[0]['work_description'],rows[1]['work_description'])
        self.assertNotIn('work_description',rows[2])

    def test_calibre_tags_preserve_user_tags_and_dedupe_case_insensitively(self):
        self.assertEqual(
            ('Personal', 'MangaNana', 'Action'),
            merge_calibre_tags(('Personal','manganana'),('Action','action')),
        )

    def test_trusted_canonical_creator_spelling_wins_over_provider_style_casing(self):
        rows=enrich_content_results(
            (content('Death Note', author='OBATA Takeshi', year=2003),),
            (external('Death Note', authors=('Takeshi Obata',), year=2003),),
        )
        self.assertEqual('Takeshi Obata',rows[0]['canonical_author'])

    def test_one_piece_creator_is_shared_across_confident_standard_family(self):
        rows=enrich_content_results((
            content('One Piece','mangadex',author='ODA Eiichiro',year=1997),
            content('One Piece','mangapill'),
            content('One Piece','weebcentral',author='Eiichiro Oda'),
        ),(external('One Piece',authors=('Eiichiro Oda',),year=1997,rating=8.5),))
        self.assertEqual(['Eiichiro Oda'] * 3,[row['canonical_author'] for row in rows])
        self.assertEqual(['One Piece'] * 3,[row['canonical_title'] for row in rows])
        self.assertEqual(1,len({row['work_family_id'] for row in rows}))

    def test_creator_acronyms_are_never_reformatted(self):
        self.assertEqual('ONE',canonical_creator_value((external('One Punch Man',authors=('ONE',)),)))
        self.assertEqual('CLAMP',canonical_creator_value((external('Cardcaptor Sakura',authors=('CLAMP',)),)))

    def test_creator_without_trusted_enrichment_keeps_provider_value(self):
        self.assertEqual('OBATA Takeshi',canonical_creator_value((), 'OBATA Takeshi'))

    def test_prefer_colored_and_explicit_fan_intent_have_expected_precedence(self):
        standard = content('One Punch Man', edition='standard')
        official = content('One Punch Man Official Colored')
        fan = content('One Punch Man Fan Colored')
        self.assertIs(standard, standard)
        normal = rank_canonical_results('One Punch Man', (fan, official, standard), False)
        colored = rank_canonical_results('One Punch Man', (standard, fan, official), True)
        explicit = rank_canonical_results('One Punch Man fan colored', (standard, official, fan), False)
        self.assertEqual(EditionClass.STANDARD, edition_classification(normal[0].group.results[0]))
        self.assertEqual(EditionClass.OFFICIAL_COLOR, edition_classification(colored[0].group.results[0]))
        self.assertEqual(EditionClass.FAN_COLOR, edition_classification(explicit[0].group.results[0]))

    def test_consensus_and_query_relative_popularity_are_separate(self):
        ani = external('A', 'anilist', rating=9.0, readers=100000)
        kitsu = external('A', 'kitsu', rating=10.0, samples=5, readers=100)
        self.assertLess(consensus_rating((ani, kitsu)), 9.3)
        values = normalized_popularity({'a': (ani,), 'b': (external('B', readers=10),)})
        self.assertGreater(values['a'], values['b'])

    def test_trusted_alias_is_single_and_bounded(self):
        ani = external('Attack on Titan', 'anilist', aliases=('Shingeki no Kyojin', '進撃の巨人'))
        kitsu = external('Attack on Titan', 'kitsu', aliases=('Shingeki no Kyojin',))
        self.assertEqual('Attack on Titan', trusted_alias_for_query('Shingeki no Kyojin', (ani,kitsu)))
        self.assertEqual('', trusted_alias_for_query('Shingeki no Kyojin', (ani,)))

    def test_late_enrichment_preserves_provider_identity_sequence(self):
        base=(
            content('JoJolion Adventure','zzz'),
            content('Unrelated Provider Label','aaa',external_ids={'mal_id':'42'}),
        )
        visible=tuple(row.provider_key for row in rank_provider_results('JoJolion',base))
        candidate=ExternalMangaCandidate(
            service='anilist',external_id='42',primary_title='JoJolion',
            cross_ids={'mal_id':'42'},rating=RatingSignal(9.1,100,'anilist'),
            popularity=PopularitySignal(1000,100,None,'anilist'),
        )
        enriched=enrich_content_results(base,(candidate,))
        overlay_sequence=tuple(
            (row.get('source_id'),row.get('id') or row.get('url')) for row in enriched
        )
        self.assertEqual(tuple((row['source_id'],row['id']) for row in base),overlay_sequence)
        # Re-ranking enriched aliases would change the display order, which is
        # exactly why the UI applies these rows as an in-place overlay instead.
        self.assertNotEqual(
            visible,tuple(row.provider_key for row in rank_provider_results('JoJolion',enriched))
        )


if __name__ == '__main__':
    unittest.main()
