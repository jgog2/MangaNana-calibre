import unittest

from search_ranking import (
    MatchTier,
    PopularitySignals,
    match_result,
    rank_canonical_results,
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

    def test_bayesian_rating_does_not_reward_tiny_vote_count_overwhelmingly(self):
        tiny = PopularitySignals(rating=9.8, rating_count=12)
        established = PopularitySignals(rating=9.2, rating_count=45000)
        self.assertGreater(established.bounded_score, tiny.bounded_score)


if __name__ == '__main__':
    unittest.main()
