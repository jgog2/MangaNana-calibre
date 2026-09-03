import unittest

from search_ranking import (
    AcquisitionFitness,
    MatchTier,
    PopularitySignals,
    match_result,
    present_search_candidate,
    rank_canonical_results,
    rank_provider_results,
)


def result(source_id, title, *, aliases=(), badge='', full_title='', popularity=None):
    return {
        'source_id': source_id,
        'source_name': source_id.title(),
        'id': source_id + '-' + title,
        'title': title,
        'full_title': full_title or title,
        'alternate_titles': list(aliases),
        'badge': badge,
        'popularity': popularity or {},
    }


class SearchRankingTests(unittest.TestCase):
    def test_presentation_fills_or_normalizes_creator_without_erasing_editions(self):
        overlay={'canonical_author':'Tatsuki Fujimoto','canonical_title':'Chainsaw Man',
                 'canonical_aliases':['チェンソーマン'],'rating_display':'8.5','work_family_id':'chainsaw-man'}
        missing=present_search_candidate(result('mangapill','Chainsaw Man'),overlay)
        ordered=result('mangadex','Chainsaw Man'); ordered['author']='Fujimoto Tatsuki'
        conflict=result('weebcentral','Chainsaw Man'); conflict['author']='Another Creator'
        colored=present_search_candidate(result('mangapill','Chainsaw Man Official Colored'),overlay)
        self.assertEqual('Tatsuki Fujimoto',missing.display_creator)
        self.assertEqual('Tatsuki Fujimoto',present_search_candidate(ordered,overlay).display_creator)
        self.assertEqual('Another Creator',present_search_candidate(conflict,overlay).display_creator)
        self.assertEqual(('Chainsaw Man Official Colored','8.5'),(colored.display_title,colored.display_rating))
        record=missing.as_record()
        self.assertEqual(('chainsaw-man','Chainsaw Man','Tatsuki Fujimoto',['チェンソーマン']),(
            record['work_family_id'],record['canonical_title'],record['canonical_author'],record['canonical_aliases'],
        ))

    def test_one_piece_creator_propagates_without_replacing_edition_title(self):
        overlay={'canonical_author':'Eiichiro Oda','canonical_title':'One Piece',
                 'canonical_aliases':['ONE PIECE'],'work_family_id':'one-piece'}
        blank=result('mangapill','One Piece')
        ordered=result('mangadex','One Piece'); ordered['author']='ODA Eiichiro'
        colored=result('weebcentral','One Piece Official Colored')
        self.assertEqual('Eiichiro Oda',present_search_candidate(blank,overlay).display_creator)
        self.assertEqual('Eiichiro Oda',present_search_candidate(ordered,overlay).display_creator)
        self.assertEqual('One Piece Official Colored',present_search_candidate(colored,overlay).display_title)

    def test_cached_canonical_creator_reaches_live_presentation_and_preserves_cover(self):
        cards=[]
        for source in ('mangadex','mangapill','weebcentral'):
            row=result(source,'One Piece')
            row.update({
                'canonical_author':'Eiichiro Oda','canonical_title':'One Piece',
                'canonical_work_id':'anilist:21','work_family_id':'one-piece',
                'rating_display':'8.5/10','cover_url':f'https://{source}/cover.jpg',
            })
            cards.append(present_search_candidate(row).as_record())
        self.assertEqual(['Eiichiro Oda'] * 3,[row['author'] for row in cards])
        self.assertEqual(['8.5/10'] * 3,[row['rating_display'] for row in cards])
        self.assertEqual(3,len({row['cover_url'] for row in cards}))
        self.assertEqual(3,len({(row['source_id'],row['id']) for row in cards}))

    def test_presentation_serializes_trusted_creator_aliases(self):
        row=result('mangapill','Bleach'); row['author']='Kubo Tite'
        record=present_search_candidate(row,{
            'canonical_author':'Tite Kubo','canonical_title':'Bleach',
            'canonical_creator_aliases':('Tite Kubo','Kubo Tite'),
            'work_family_id':'canonical:bleach:original',
        },AcquisitionFitness.DIRECT,'qualified',698).as_record()
        self.assertEqual(['Tite Kubo','Kubo Tite'],record['canonical_creator_aliases'])
        self.assertEqual(('Tite Kubo','direct',698),(
            record['author'],record['_acquisition_fitness'],record['_qualification_chapter_count'],
        ))

    def test_direct_fitness_beats_provider_preference_without_hiding_cards(self):
        dex=result('mangadex','One-Punch Man')
        pill=result('mangapill','One-Punch Man')
        dex['_acquisition_fitness']=AcquisitionFitness.FALLBACK_ONLY.value
        pill['_acquisition_fitness']=AcquisitionFitness.DIRECT.value
        pill['_qualification_chapter_count']=312
        ranked=rank_provider_results('One Punch Man',(dex,pill))
        self.assertEqual(['mangapill','mangadex'],[row.result['source_id'] for row in ranked])

    def test_unknown_beats_unavailable_and_provider_preference_breaks_equal_ties(self):
        dex=result('mangadex','Series'); pill=result('mangapill','Series')
        dex['_acquisition_fitness']='unavailable'; pill['_acquisition_fitness']='unknown'
        self.assertEqual('mangapill',rank_provider_results('Series',(dex,pill))[0].result['source_id'])
        dex['_acquisition_fitness']=pill['_acquisition_fitness']='direct'
        self.assertEqual('mangadex',rank_provider_results('Series',(pill,dex))[0].result['source_id'])

    def test_exact_primary_alias_and_hyphen_normalization_have_clear_tiers(self):
        primary = match_result('Chainsaw Man', result('dex', 'Chainsaw Man'))
        alias = match_result('Shingeki no Kyojin', result('dex', 'Attack on Titan', aliases=('Shingeki no Kyojin',)))
        leading = match_result('One Punch', result('dex', 'One-Punch Man'))
        self.assertEqual(MatchTier.EXACT_PRIMARY, primary.tier)
        self.assertEqual(MatchTier.EXACT_ALIAS, alias.tier)
        self.assertEqual(MatchTier.LEADING_PHRASE, leading.tier)

    def test_one_punch_main_work_outranks_noisy_incidental_title(self):
        ranked = rank_canonical_results('One Punch', (
            result('dex', 'A Crossover With One Punch in Another World Extra Story'),
            result('pill', 'One-Punch Man'),
            result('weeb', 'One Punch Man: Road to Hero Special Edition Side Story'),
        ))
        self.assertEqual('One-Punch Man', ranked[0].group.display_title)
        self.assertNotIn(
            'A Crossover With One Punch in Another World Extra Story',
            [row.group.display_title for row in ranked],
        )

    def test_single_token_jojo_is_useful_but_short_generic_man_is_not_broad(self):
        ranked = rank_canonical_results('Jojo', (
            result('dex', "JoJo's Bizarre Adventure Part 8 - JoJolion"),
            result('pill', 'A Girl Who Read Jojo and Changed Her Life'),
        ))
        self.assertEqual(1, len(ranked))
        self.assertTrue(ranked[0].group.display_title.startswith("JoJo's"))
        self.assertEqual((), rank_canonical_results('Man', (
            result('dex', 'Chainsaw Man'), result('pill', 'One Punch Man'),
        )))

    def test_edition_intent_prefers_standard_normally_and_color_when_requested(self):
        standard = result('dex', 'One Punch Man')
        colored = result('pill', 'One Punch Man', badge='COLOR', full_title='One Punch Man Digital Colored Comics')
        fan = result('weeb', 'One Punch Man', badge='FAN COLOR', full_title='One Punch Man Fan Colored')
        normal_ranked = rank_canonical_results('One Punch Man', (fan, colored, standard))
        self.assertEqual('original', __import__('canonical_identity').edition_identity(normal_ranked[0].group.results[0]))
        color_ranked = rank_canonical_results('One Punch Man colored', (standard, fan, colored))
        self.assertEqual('official_color', __import__('canonical_identity').edition_identity(color_ranked[0].group.results[0]))

    def test_regression_corpus_all_has_a_plausible_top_result(self):
        cases = (
            ('One Punch', 'One-Punch Man'),
            ('One Punch Man', 'One Punch Man'),
            ('One Punch Man colored', 'One Punch Man Colored'),
            ('Chainsaw Man', 'Chainsaw Man'),
            ('Attack on Titan', 'Attack on Titan'),
            ('Shingeki no Kyojin', 'Attack on Titan'),
            ('Jojo', "JoJo's Bizarre Adventure Part 7 Steel Ball Run"),
            ('JoJolion', 'JoJolion'),
            ('One Piece', 'One Piece'),
            ('Steel Ball Run', 'Steel Ball Run'),
        )
        for query, title in cases:
            aliases = ('Shingeki no Kyojin',) if title == 'Attack on Titan' else ()
            with self.subTest(query=query):
                ranked = rank_canonical_results(query, (result('dex', title, aliases=aliases),))
                self.assertEqual(title, ranked[0].group.display_title)

    def test_popularity_is_unknown_when_missing_and_cannot_rescue_weak_text(self):
        unknown = PopularitySignals()
        self.assertFalse(unknown.known)
        self.assertIsNone(unknown.bounded_score)
        ranked = rank_canonical_results('Chainsaw Man', (
            result('popular', 'Unrelated Hero', popularity={'rating': 10, 'rating_count': 1000000, 'follows': 999999}),
            result('exact', 'Chainsaw Man'),
        ))
        self.assertEqual(['Chainsaw Man'], [row.group.display_title for row in ranked])

    def test_normalized_popularity_only_reorders_inside_the_same_relevance_tier(self):
        exact = result('exact', 'One Piece', popularity={'normalized': 0.0})
        weaker = result('weak', 'One Piece Episode A', popularity={'normalized': 1.0})
        ranked = rank_canonical_results('One Piece', (weaker, exact))
        self.assertEqual('One Piece', ranked[0].group.display_title)

    def test_bayesian_rating_does_not_reward_tiny_vote_count_overwhelmingly(self):
        tiny = PopularitySignals(rating=9.8, rating_count=12)
        established = PopularitySignals(rating=9.2, rating_count=45000)
        self.assertGreater(established.bounded_score, tiny.bounded_score)

    def test_provider_local_results_are_not_cross_provider_deduplicated(self):
        rows=(
            result('mangadex','JoJolion'),
            result('mangapill','JoJolion'),
            result('weebcentral','JoJolion'),
        )
        ranked=rank_provider_results('JoJolion',rows)
        self.assertEqual(3,len(ranked))
        self.assertEqual(
            {'mangadex','mangapill','weebcentral'},
            {row.result['source_id'] for row in ranked},
        )

    def test_same_provider_exact_id_deduplicates_but_other_ids_survive(self):
        original=result('mangadex','JoJolion')
        duplicate=dict(original)
        alternate=result('mangadex','JoJolion Color-ban')
        alternate['id']='distinct-edition-id'
        ranked=rank_provider_results('JoJolion',(duplicate,alternate,original))
        self.assertEqual(2,len(ranked))
        self.assertEqual(
            {original['id'],'distinct-edition-id'},
            {row.result['id'] for row in ranked},
        )

    def test_weak_provider_result_ranks_low_instead_of_disappearing(self):
        weak=result('mangapill','A Provider Suggested Side Story')
        exact=result('mangadex','JoJolion')
        ranked=rank_provider_results('JoJolion',(weak,exact))
        self.assertEqual(['JoJolion','A Provider Suggested Side Story'],[row.result['title'] for row in ranked])
        self.assertEqual(MatchTier.PROVIDER_WEAK,ranked[-1].match.tier)

    def test_provider_response_order_does_not_change_final_order(self):
        rows=(
            {**result('mangadex','JoJolion'),'provider_result_order':0},
            {**result('mangapill','JoJolion'),'provider_result_order':0},
            {**result('weebcentral','JoJolion'),'provider_result_order':0},
        )
        first=rank_provider_results('JoJolion',rows)
        second=rank_provider_results('JoJolion',tuple(reversed(rows)))
        self.assertEqual([row.provider_key for row in first],[row.provider_key for row in second])

    def test_prefer_colored_is_a_local_rerank_without_removing_standard(self):
        standard=result('mangadex','JoJolion')
        colored=result('mangadex','JoJolion Color-ban',badge='COLOR')
        normal=rank_provider_results('JoJolion',(colored,standard),False)
        preferred=rank_provider_results('JoJolion',(standard,colored),True)
        self.assertEqual(2,len(preferred))
        self.assertEqual('JoJolion Color-ban',preferred[0].result['title'])
        self.assertEqual({'JoJolion','JoJolion Color-ban'},{row.result['title'] for row in normal})


if __name__ == '__main__':
    unittest.main()
