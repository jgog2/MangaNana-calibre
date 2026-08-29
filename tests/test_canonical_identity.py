import unittest

from canonical_identity import (
    filter_relevant_results,
    group_canonical_results,
    normalize_identity_text,
    source_badge_specs,
)


def result(source_id, title, *, aliases=(), author='', year=None, full_title='', badge=''):
    names = {'mangadex': 'MangaDex', 'mangapill': 'MangaPill', 'third': 'Third Source'}
    return {
        'source_id': source_id, 'source_name': names[source_id], 'id': source_id + '-id',
        'title': title, 'full_title': full_title or title,
        'alternate_titles': list(aliases), 'author': author, 'year': year, 'badge': badge,
    }


class CanonicalIdentityTests(unittest.TestCase):
    def test_unicode_case_whitespace_and_punctuation_normalization(self):
        self.assertEqual(normalize_identity_text('  ATTACK—ON   TITAN '), 'attack on titan')
        self.assertEqual(normalize_identity_text('Ａｔｔａｃｋ on Titan'), 'attack on titan')

    def test_attack_on_titan_groups_through_english_romaji_and_japanese_aliases(self):
        rows = [
            result('mangadex', 'Attack on Titan', aliases=('Shingeki no Kyojin', '進撃の巨人'), author='Hajime Isayama'),
            result('mangapill', 'Shingeki no Kyojin'),
            result('third', '進撃の巨人', author='Hajime Isayama'),
        ]
        groups = group_canonical_results(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].display_title, 'Attack on Titan')
        self.assertEqual(groups[0].source_ids, ('mangadex', 'mangapill', 'third'))
        self.assertEqual(groups[0].confidence, 'high')
        self.assertIn('進撃の巨人', groups[0].aliases)

    def test_substring_title_is_not_identity(self):
        groups = group_canonical_results([
            result('mangadex', 'One Piece', author='Eiichiro Oda'),
            result('mangapill', 'One Piece Episode A'),
        ])
        self.assertEqual(len(groups), 2)

    def test_colored_and_original_editions_remain_separate(self):
        groups = group_canonical_results([
            result('mangadex', 'Berserk', full_title='Berserk Official Colored', badge='COLOR'),
            result('mangapill', 'Berserk'),
        ])
        self.assertEqual(len(groups), 2)

    def test_fan_colored_and_official_colored_remain_separate(self):
        groups = group_canonical_results([
            result('mangadex', 'Example', full_title='Example Fan Colored', badge='FAN COLOR'),
            result('mangapill', 'Example Official Colored'),
        ])
        self.assertEqual(len(groups), 2)

    def test_same_title_and_author_groups(self):
        groups = group_canonical_results([
            result('mangadex', 'Dorohedoro', author='Q Hayashida'),
            result('mangapill', 'Dorohedoro', author='Q Hayashida'),
        ])
        self.assertEqual(len(groups), 1)
        self.assertIn('matching author', groups[0].reason)

    def test_same_title_with_conflicting_authors_stays_separate(self):
        groups = group_canonical_results([
            result('mangadex', 'Example', author='Author One'),
            result('mangapill', 'Example', author='Author Two'),
        ])
        self.assertEqual(len(groups), 2)

    def test_missing_aliases_do_not_break_exact_title_grouping(self):
        groups = group_canonical_results([
            result('mangadex', 'Monster', author='Naoki Urasawa'),
            result('mangapill', 'Monster'),
        ])
        self.assertEqual(len(groups), 1)

    def test_grouping_order_and_provenance_are_deterministic(self):
        rows = [
            result('mangadex', 'First', aliases=('Alias One',)),
            result('mangadex', 'Second'),
            result('mangapill', 'Alias One'),
        ]
        first = group_canonical_results(rows)
        second = group_canonical_results(rows)
        self.assertEqual(first, second)
        self.assertEqual([group.display_title for group in first], ['First', 'Second'])
        self.assertEqual(first[0].source_names, ('MangaDex', 'MangaPill'))
        self.assertEqual([row['id'] for row in first[0].results], ['mangadex-id', 'mangapill-id'])

    def test_weak_incidental_result_is_filtered(self):
        rows = [
            result('mangadex', 'Attack on Titan', aliases=('Shingeki no Kyojin',)),
            result('mangapill', "My Fake Girlfriend's Defending Against Their Attacks"),
        ]
        filtered = filter_relevant_results('Attack on Titan', rows)
        self.assertEqual([row['title'] for row in filtered], ['Attack on Titan'])

    def test_exact_alias_and_canonical_companion_are_preserved(self):
        rows = [
            result('mangadex', 'Attack on Titan', aliases=('Shingeki no Kyojin',)),
            result('mangapill', 'Shingeki no Kyojin'),
        ]
        filtered = filter_relevant_results('Attack on Titan', rows)
        self.assertEqual([row['source_id'] for row in filtered], ['mangadex', 'mangapill'])
        self.assertEqual(len(group_canonical_results(filtered)), 1)

    def test_strong_all_token_result_remains(self):
        filtered = filter_relevant_results('Attack on Titan', [
            result('mangapill', 'The Attack on Titan Guide'),
        ])
        self.assertEqual(len(filtered), 1)

    def test_source_badge_metadata_is_compact_and_deterministic(self):
        self.assertEqual(source_badge_specs(('MangaDex', 'MangaPill', 'MangaDex')), (
            {'text': 'MangaDex', 'kind': 'source'},
            {'text': 'MangaPill', 'kind': 'source'},
        ))


if __name__ == '__main__':
    unittest.main()
