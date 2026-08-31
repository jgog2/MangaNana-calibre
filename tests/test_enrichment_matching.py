import unittest

from canonical_identity import edition_classification, edition_display_label
from enrichment_matching import (
    consensus_rating, enrich_content_results, match_external_identity,
    normalized_popularity, trusted_alias_for_query,
)
from enrichment_model import (
    EditionClass, ExternalMangaCandidate, IdentityConfidence,
    PopularitySignal, RatingSignal,
)
from search_ranking import rank_canonical_results


def external(title, service='anilist', *, aliases=(), authors=(), year=None,
             rating=8.0, samples=None, readers=1000, favourites=100):
    return ExternalMangaCandidate(
        service=service, external_id=service + '-1', primary_title=title,
        aliases=tuple(aliases), authors=tuple(authors), start_year=year,
        cross_ids={service + '_id': service + '-1'},
        rating=RatingSignal(rating, samples, service),
        popularity=PopularitySignal(readers, favourites, None, service),
    )


def content(title, source='mangadex', **extra):
    return {'source_id': source, 'source_name': source, 'id': source + title,
            'title': title, 'full_title': title, 'alternate_titles': [], **extra}


class EnrichmentMatchingTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
