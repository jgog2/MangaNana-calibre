import unittest

from mangabaka_reference import MangaBakaPublicationAdapter


def _series(series_id, title, aliases=(), **extra):
    return {
        'id': series_id, 'type': 'manga', 'canonical_url': 'https://mangabaka.org/manga/%s' % series_id,
        'title': title, 'native_title': None, 'romanized_title': None,
        'secondary_titles': {'ja': [{'type': 'alternative', 'title': value} for value in aliases]},
        'cover': {'raw': {'url': 'https://images.example/%s.jpg' % series_id}},
        'description': 'English description',
        'tags': [{'name': 'Mystery'}, {'name': 'Psychological'}],
        'source': {'anilist': {'id': 30021}, 'kitsu': {'id': 57}},
        **extra,
    }


class MangaBakaReferenceTests(unittest.TestCase):
    def adapter(self, search_rows, detail_rows=None):
        detail_rows = detail_rows or {str(row['id']): row for row in search_rows}
        def request(url):
            if '/series/search?' in url:
                return {'status': 200, 'pagination': {'next': None, 'page': 1, 'limit': 50}, 'data': search_rows}
            series_id = url.split('/series/')[1].split('?')[0]
            return {'status': 200, 'data': detail_rows.get(series_id)}
        return MangaBakaPublicationAdapter(request)

    def test_stable_id_alias_and_external_ids_are_explicit(self):
        row = _series(1824, 'DEATH NOTE', ('Death Note',))
        adapter = self.adapter([row])
        match = adapter.match_publication({'title': 'Death Note'})
        self.assertEqual(('1824', 'confident'), (match.publication_id, match.confidence))
        self.assertEqual({'anilist': 30021, 'kitsu': 57}, adapter.get_external_ids(match))

    def test_ambiguous_exact_results_fail_closed(self):
        adapter = self.adapter([_series(1, 'Death Note'), _series(2, 'Death Note')])
        self.assertEqual('ambiguous', adapter.match_publication({'title': 'Death Note'}).confidence)

    def test_attack_alias_and_jojolion_part_are_exact(self):
        attack = self.adapter([_series(4024, 'ATTACK ON TITAN', ('Shingeki no Kyojin',))])
        self.assertEqual('4024', attack.match_publication({'title': 'Shingeki no Kyojin'}).publication_id)
        jojo = self.adapter([_series(1406, 'JoJo no Kimyou na Bouken: JoJolion', ('ジョジョの奇妙な冒険 ジョジョリオン',))])
        self.assertEqual('1406', jojo.match_publication({
            'title': 'JoJo no Kimyou na Bouken: JoJolion', 'aliases': ('JoJolion',),
        }).publication_id)

    def test_volume_artwork_and_language_claims_fail_closed(self):
        adapter = self.adapter([_series(377, 'ONE PIECE', final_volume=115)])
        match = adapter.match_publication({'title': 'ONE PIECE'})
        self.assertEqual((), adapter.get_volume_list(match))
        self.assertEqual((), adapter.get_volume_covers(match))
        artwork = adapter.get_edition_artwork(match)
        self.assertEqual(('work', 'work_level'), (artwork[0].artwork_type, artwork[0].confidence))
        self.assertNotIn('language', artwork[0].__dict__)

    def test_missing_optional_fields_and_bad_detail_fail_closed(self):
        row = _series(1406, 'JoJo no Kimyou na Bouken: JoJolion', tags=[], source={})
        adapter = self.adapter([row], {'1406': {'id': 1406, 'description': None}})
        match = adapter.match_publication({'title': 'JoJo no Kimyou na Bouken: JoJolion'})
        self.assertEqual((), adapter.get_tags(match))
        self.assertEqual('', adapter.get_description(match))
        self.assertEqual((), adapter.get_edition_artwork(match))

    def test_pagination_is_not_silently_followed(self):
        row = _series(377, 'ONE PIECE')
        adapter = self.adapter([row])
        match = adapter.match_publication({'title': 'ONE PIECE'})
        self.assertEqual('377', match.publication_id)
        self.assertEqual(1, adapter.request_count)


if __name__ == '__main__':
    unittest.main()
