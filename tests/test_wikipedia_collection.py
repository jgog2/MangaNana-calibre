import tempfile
import unittest
from pathlib import Path

from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService
from reference_metadata import PublicationArtwork, PublicationChapter, PublicationMatch, PublicationVolume
from search_cache import IDENTITY_TTL, SearchMetadataCache
from wikipedia_reference import (
    WikipediaPublicationAdapter, WikipediaPublicationSegment, _aggregate_segments,
)


def graphic(volume, rows):
    bullets = '\n'.join(f'* {number}. {title}' for number, title in rows)
    return f'{{{{Graphic novel list|VolumeNumber={volume}|ChapterList=\n{bullets}\n}}}}'


class WikipediaFixture:
    def __init__(self, pages, search_title='Test', search_rows=None):
        self.pages = pages
        self.search_title = search_title
        self.search_rows = search_rows
        self.calls = []
        self.failure = None

    def __call__(self, params):
        self.calls.append(dict(params))
        if params['action'] == 'query':
            return {'query': {'search': self.search_rows or [
                {'pageid': 1, 'title': self.search_title},
            ]}}
        title = params['page']
        if self.failure == title:
            raise RuntimeError('HTTP 429 fixture')
        pageid, revid, text = self.pages[title]
        return {'parse': {
            'title': title, 'pageid': pageid, 'revid': revid,
            'wikitext': {'*': text},
        }}


def collection_pages(extra_index='', segment_two=None):
    return {
        'Test': (1, 101, '{{Further|Lists of Test chapters}}'),
        'Lists of Test chapters': (
            2, 102,
            '[[List of Test chapters (1–2)]]\n'
            '[[List of Test chapters (1–2)]]\n'
            '[[List of Test chapters (3–4)]]\n' + extra_index,
        ),
        'List of Test chapters (1–2)': (
            3, 103,
            graphic('1', (('1', 'One'), ('2', 'Two'))) +
            '\n[[Lists of Test chapters]]',
        ),
        'List of Test chapters (3–4)': (
            4, 104,
            segment_two or graphic('2', (('3', 'Three'), ('4', 'Four'))),
        ),
        'List of Test chapters (5–6)': (
            5, 105, graphic('3', (('5', 'Five'), ('6', 'Six'))),
        ),
    }


def reused_label_pages():
    return {
        'Test': (1, 101, '{{Further|Lists of Test chapters}}'),
        'Lists of Test chapters': (2, 102, '[[List of Test chapters (0–1)]]'),
        'List of Test chapters (0–1)': (
            3, 103,
            '{{Graphic novel list|VolumeNumber=23|ChapterList='
            '{{Numbered list|start=0|Side A}}{{Numbered list|start=0|Side B}}\n'
            '{{Numbered list|start=1|One}}\n}}',
        ),
    }


def match(edition='original'):
    return PublicationMatch('wikipedia', '1', 'Test', 'confident', 'fixture', edition=edition)


class WikipediaCollectionTests(unittest.TestCase):
    def test_manga_disambiguation_requires_creator_corroboration(self):
        rows = [
            {'pageid': 1, 'title': 'Bleach', 'snippet': 'Chemical compound'},
            {'pageid': 2, 'title': 'Bleach (manga)',
             'snippet': 'Japanese manga series written and illustrated by Tite Kubo'},
        ]
        adapter = WikipediaPublicationAdapter(WikipediaFixture({}, search_rows=rows))
        selected = adapter.match_publication({
            'title': 'Bleach', 'author': 'Tite Kubo', 'edition': 'original',
        })
        self.assertEqual(('confident', 'Bleach (manga)'), (selected.confidence, selected.title))
        ambiguous = WikipediaPublicationAdapter(WikipediaFixture({}, search_rows=rows)).match_publication({
            'title': 'Bleach', 'edition': 'original',
        })
        self.assertEqual('ambiguous', ambiguous.confidence)
        reordered = WikipediaPublicationAdapter(WikipediaFixture({}, search_rows=rows)).match_publication({
            'title': 'Bleach', 'author': 'Kubo Tite',
            'creator_aliases': ('Kubo Tite', 'Tite Kubo'),
            'identity_confidence': 'high', 'edition': 'original',
        })
        self.assertEqual(('confident', 'Bleach (manga)'),
                         (reordered.confidence, reordered.title))
        untrusted = WikipediaPublicationAdapter(WikipediaFixture({}, search_rows=rows)).match_publication({
            'title': 'Bleach', 'author': 'Kubo Tite',
            'creator_aliases': ('Tite Kubo',), 'edition': 'original',
        })
        self.assertEqual('ambiguous', untrusted.confidence)

    def test_manga_disambiguation_accepts_any_trusted_creator_component(self):
        rows=[
            {'pageid':1,'title':'Example','snippet':'Unrelated subject'},
            {'pageid':2,'title':'Example (manga)',
             'snippet':'Japanese manga series created by Creator A'},
        ]
        selected=WikipediaPublicationAdapter(WikipediaFixture({},search_rows=rows)).match_publication({
            'title':'Example','author':'Creator A, Creator B',
            'creators':('Creator A','Creator B'),
            'creator_aliases':('Creator A','Creator B'),
            'identity_confidence':'high','edition':'original',
        })
        self.assertEqual(('confident','Example (manga)'),
                         (selected.confidence,selected.title))

    def test_manga_disambiguation_accepts_bounded_creator_romanization_variant(self):
        rows=[
            {'pageid':1,'title':'Berserk','snippet':'Unrelated subject'},
            {'pageid':2,'title':'Berserk (manga)',
             'snippet':'Japanese manga series created by Kentaro Miura'},
        ]
        selected=WikipediaPublicationAdapter(WikipediaFixture({},search_rows=rows)).match_publication({
            'title':'Berserk','author':'Kentarou Miura, Studio Gaga',
            'creators':('Kentarou Miura','Studio Gaga'),
            'creator_aliases':('Kentarou Miura','Studio Gaga'),
            'identity_confidence':'high','edition':'original',
        })
        self.assertEqual(('confident','Berserk (manga)'),
                         (selected.confidence,selected.title))

    def test_volume_index_explicitly_links_same_work_chapter_segments(self):
        pages = {
            'Test': (1, 101, '| volume_list = List of Test volumes\n{{Further|List of Test volumes}}'),
            'List of Test volumes': (2, 102,
                '{{Main|List of Test chapters (1–2)}}\n[[List of Other Manga chapters]]\n'
                '[[Category:Test volumes]]'),
            'List of Test chapters (1–2)': (3, 103, graphic('1', (('1', 'One'), ('2', 'Two')))),
        }
        fixture = WikipediaFixture(pages)
        resolved = WikipediaPublicationAdapter(fixture).resolve_publication(match())
        self.assertEqual('valid_complete', resolved['status'])
        self.assertEqual(['1', '2'], [row.number for row in resolved['chapters']])
        self.assertEqual('publication_index', resolved['collection'].index_pages[0]['kind'])
        fetched = [row['page'] for row in fixture.calls if row['action'] == 'parse']
        self.assertNotIn('List of Other Manga chapters', fetched)
        self.assertNotIn('Category:Test volumes', fetched)

    def test_main_article_escape_and_manga_volume_index_are_explicit_generic_links(self):
        pages = {
            'Test': (1, 101, '| volume_list = [[List of Test manga volumes]]'),
            'List of Test manga volumes': (
                2, 102, '{{Main article|:List of Test volumes (1–20)}}'
            ),
            'List of Test volumes (1–20)': (
                3, 103, graphic('1', (('1', 'One'), ('2', 'Two')))
            ),
        }
        fixture = WikipediaFixture(pages)
        resolved = WikipediaPublicationAdapter(fixture).resolve_publication(match())
        self.assertEqual(('valid_complete', ['1', '2']), (
            resolved['status'], [row.number for row in resolved['chapters']],
        ))

    def test_ordered_html_value_sets_explicit_start_and_comments_do_not_match(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=1|ChapterList=\n'
            '<!-- Do not use {{Numbered list}} here. -->\n'
            '#<li value="8">Eight</li>\n#Nine\n}}')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual([('8', 'Eight'), ('9', 'Nine')], [
            (row.number, row.title) for row in resolved['chapters']
        ])

    def test_round_bullets_are_explicit_graphic_list_chapter_identifiers(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=1|ChapterList=\n'
            '* Round 001: First\n* Round 002: Second\n}}')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual(['001', '002'], [row.number for row in resolved['chapters']])

    def test_numbered_list_start_allows_a_trailing_source_comment(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=1|ChapterList='
            '{{Numbered list|start=851 <!-- source note -->|First|Second}}}}')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual(['851', '852'], [row.number for row in resolved['chapters']])

    def test_explicit_uncollected_section_has_no_volume_and_overrides_containment(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=13|ChapterList=\n* 083. Omitted\n}}\n'
            '==Chapters not released in collected volumes==\n'
            '* 083. Omitted\n* 384. Current\n'
            '==References==\n')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual([('083', '', 'uncollected'), ('384', '', 'uncollected')], [
            (row.number, row.volume, row.kind) for row in resolved['chapters']
        ])
        wiki = {
            'status': resolved['status'],
            'chapters': [row.__dict__ for row in resolved['chapters']],
            'volumes': [row.__dict__ for row in resolved['volumes']],
        }
        manifest = PublicationManifestBuilder(
            {'canonical_identity': 'test', 'title': 'Test'}, 'original'
        ).apply_wikipedia(wiki).build()
        projection = build_publication_projection(
            [{'chapter': '83', 'title': ''}, {'chapter': '384', 'title': ''}],
            manifest, 'provider', 'provider',
        )
        self.assertEqual((0, 2, ['Omitted', 'Current']), (
            projection.coverage['reference_explicit'],
            projection.coverage['unmapped_provider_chapters'],
            [row.resolved_title.value for row in projection.chapters],
        ))

    def test_not_yet_published_volume_format_numbered_list_is_uncollected(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=1|ChapterList=\n* 1. One\n}}\n'
            '==Chapters not yet published in volume format==\n'
            '{{Numbered list|start=2|Two|Three}}\n')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual([('1', '1', 'chapter'), ('2', '', 'uncollected'),
                          ('3', '', 'uncollected')], [
            (row.number, row.volume, row.kind) for row in resolved['chapters']
        ])

    def test_not_yet_in_tankobon_rounds_are_uncollected(self):
        pages = {'Test': (1, 101,
            '{{Graphic novel list|VolumeNumber=1|ChapterList=\n* Round 001: One\n}}\n'
            "==Chapters not yet in ''tankōbon'' format==\n"
            '* Round 002: Two\n')}
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual([('001', '1', 'chapter'), ('002', '', 'uncollected')], [
            (row.number, row.volume, row.kind) for row in resolved['chapters']
        ])

    def test_manga_disambiguated_root_accepts_its_explicit_base_title_index(self):
        pages = {
            'Test (manga)': (1, 101, '| volume_list = List of Test volumes'),
            'List of Test volumes': (2, 102, '{{Main|List of Test chapters (1–2)}}'),
            'List of Test chapters (1–2)': (3, 103, graphic('1', (('1', 'One'), ('2', 'Two')))),
        }
        root = PublicationMatch('wikipedia', '1', 'Test (manga)', 'confident', 'fixture')
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(root)
        self.assertEqual(('valid_complete', ['1', '2']), (
            resolved['status'], [row.number for row in resolved['chapters']],
        ))

    def test_validated_indexes_deduplicate_a_shared_explicit_segment(self):
        pages = {
            'Test': (1, 101, '{{Further|List of Test volumes|List of Test publications}}'),
            'List of Test volumes': (2, 102, '{{Main|List of Test chapters (1–2)}}'),
            'List of Test publications': (3, 103, '{{Main|List of Test chapters (1–2)}}'),
            'List of Test chapters (1–2)': (4, 104, graphic('1', (('1', 'One'), ('2', 'Two')))),
        }
        fixture = WikipediaFixture(pages)
        resolved = WikipediaPublicationAdapter(fixture).resolve_publication(match())
        self.assertEqual(('valid_complete', 1, 2), (
            resolved['status'], len(resolved['collection'].segments),
            len(resolved['collection'].index_pages),
        ))
        self.assertEqual(1, [row['page'] for row in fixture.calls if row['action'] == 'parse']
                         .count('List of Test chapters (1–2)'))

    def test_explicit_negative_chapter_identifiers_remain_distinct(self):
        pages = {
            'Test': (1, 101,
                '{{Graphic novel list|VolumeNumber=1|ChapterList='
                '{{Numbered list|start=-108|Before|After}}}}'),
        }
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual(['-108', '-107'], [row.number for row in resolved['chapters']])
        wiki = {
            'status': resolved['status'],
            'chapters': [row.__dict__ for row in resolved['chapters']],
            'volumes': [row.__dict__ for row in resolved['volumes']],
        }
        manifest = PublicationManifestBuilder(
            {'canonical_identity': 'test', 'title': 'Test'}, 'original'
        ).apply_wikipedia(wiki).build()
        projection = build_publication_projection(
            [{'chapter': '-108', 'title': ''}, {'chapter': '-107', 'title': ''}],
            manifest, 'provider', 'provider',
        )
        self.assertEqual(2, projection.coverage['reference_explicit'])

    def test_explicit_discovery_rejects_unrelated_deduplicates_and_never_guesses(self):
        pages = collection_pages(
            '[[List of Other Manga chapters (1–2)]]\n[[Category:Test chapter lists]]'
        )
        fixture = WikipediaFixture(pages)
        adapter = WikipediaPublicationAdapter(fixture)
        resolved = adapter.resolve_publication(match())
        metadata = resolved['collection'].metadata()
        fetched = [row['page'] for row in fixture.calls if row['action'] == 'parse']
        self.assertEqual('valid_complete', resolved['status'])
        self.assertEqual((2, 2, 1), (
            metadata['discovered_candidates'], metadata['accepted_segments'],
            metadata['rejected_segments'],
        ))
        self.assertEqual(1, fetched.count('List of Test chapters (1–2)'))
        self.assertNotIn('List of Test chapters (5–6)', fetched)
        self.assertNotIn('List of Other Manga chapters (1–2)', fetched)
        self.assertNotIn('Category:Test chapter lists', fetched)
        self.assertEqual(['1', '2', '3', '4'], [row.number for row in resolved['chapters']])

    def test_cycle_protection_and_page_bound_fail_closed(self):
        fixture = WikipediaFixture(collection_pages())
        adapter = WikipediaPublicationAdapter(fixture)
        adapter.max_collection_pages = 2
        resolved = adapter.resolve_publication(match())
        self.assertEqual('ambiguous_collection', resolved['status'])
        self.assertEqual((), resolved['chapters'])
        self.assertLessEqual(len([row for row in fixture.calls if row['action'] == 'parse']), 3)

    def test_edition_mismatch_is_rejected_without_fetch(self):
        pages = collection_pages()
        pages['Lists of Test chapters'] = (
            2, 102, '[[List of Test chapters (colored edition)]]'
        )
        fixture = WikipediaFixture(pages)
        resolved = WikipediaPublicationAdapter(fixture).resolve_publication(match('original'))
        self.assertEqual('ambiguous_collection', resolved['status'])
        self.assertEqual(1, resolved['collection'].rejected_segments)
        self.assertNotIn(
            'List of Test chapters (colored edition)',
            [row.get('page') for row in fixture.calls],
        )

    def test_unsupported_explicit_segment_is_honest_partial(self):
        pages = collection_pages()
        pages['Lists of Test chapters'] = (
            2, 102,
            '[[List of Test chapters (1–2)]]\n[[List of Test chapters (3–4)]]',
        )
        pages['List of Test chapters (3–4)'] = (4, 104, 'Narrative only')
        resolved = WikipediaPublicationAdapter(WikipediaFixture(pages)).resolve_publication(match())
        self.assertEqual('valid_partial', resolved['status'])
        self.assertEqual(1, resolved['collection'].unsupported_segments)
        self.assertEqual(['1', '2'], [row.number for row in resolved['chapters']])

    @staticmethod
    def _segment(page, rows):
        return WikipediaPublicationSegment(
            0, page, page, '1', 'fixture', 'fixture', '1', tuple(rows),
            (PublicationVolume('1'),),
        )

    def test_aggregation_duplicate_complement_and_local_volume_conflict(self):
        first = self._segment('A', (
            PublicationChapter('01', 'One', '1', source_page='A'),
            PublicationChapter('2', '', '1', source_page='A'),
            PublicationChapter('4', 'Four', '1', source_page='A'),
        ))
        second = self._segment('B', (
            PublicationChapter('1', 'One', '1', source_page='B'),
            PublicationChapter('2', 'Two', '1', source_page='B'),
        ))
        forward = _aggregate_segments((first, second))
        reverse = _aggregate_segments((second, first))
        self.assertEqual(
            [(row.number, row.title, row.source_pages) for row in forward[0]],
            [(row.number, row.title, row.source_pages) for row in reverse[0]],
        )
        self.assertEqual((1, 1, (), ()), (forward[2], forward[3], forward[4], forward[5]))
        self.assertEqual(['1', '2', '4'], [row.number for row in forward[0]])
        conflict = self._segment('C', (
            PublicationChapter('2', 'Two', '2', source_page='C'),
        ))
        failed = _aggregate_segments((first, conflict))
        self.assertEqual(['1', '4'], [row.number for row in failed[0]])
        self.assertIn('volumes', failed[4][0])
        self.assertEqual('true_structural_conflict', failed[5][0]['classification'])

    def test_same_structure_reused_label_is_retained_as_quarantined_source_records(self):
        rows = (
            PublicationChapter('0', 'Side A', '23', source_page='Segment',
                               parser_pattern='fixture', source_page_id='10',
                               source_revision_id='20', source_record_id='10:20:0'),
            PublicationChapter('0', 'Side B', '23', source_page='Segment',
                               parser_pattern='fixture', source_page_id='10',
                               source_revision_id='20', source_record_id='10:20:1'),
            PublicationChapter('1', 'One', '23', source_page='Segment',
                               parser_pattern='fixture', source_page_id='10',
                               source_revision_id='20', source_record_id='10:20:2'),
        )
        result = _aggregate_segments((self._segment('Segment', rows),))
        self.assertEqual(['1'], [row.number for row in result[0]])
        group = result[5][0]
        self.assertEqual(('explicit_reused_label', 2, 'ambiguous_unprojected'), (
            group['classification'], group['row_count'], group['acquisition_projection'],
        ))
        self.assertEqual(['Side A', 'Side B'], [row['title'] for row in group['records']])

    def test_cross_segment_title_disagreement_is_ambiguous_and_order_deterministic(self):
        first = self._segment('A', (
            PublicationChapter('0', 'Side A', '23', source_page='A',
                               source_page_id='1', source_revision_id='1',
                               source_record_id='1:1:0'),
            PublicationChapter('1', 'One', '23', source_page='A'),
        ))
        title_conflict = self._segment('D', (
            PublicationChapter('0', 'Side B', '23', source_page='D',
                               source_page_id='2', source_revision_id='1',
                               source_record_id='2:1:0'),
        ))
        forward = _aggregate_segments((first, title_conflict))
        reverse = _aggregate_segments((title_conflict, first))
        self.assertEqual(['1'], [row.number for row in forward[0]])
        self.assertEqual('local_ambiguous_label_group', forward[5][0]['classification'])
        self.assertEqual(forward, reverse)

    def test_ambiguous_reference_label_is_not_assigned_to_one_acquisition_row(self):
        builder = PublicationManifestBuilder(
            {'canonical_identity': 'test', 'title': 'Test'}, 'original'
        ).apply_wikipedia({
            'status': 'valid_partial',
            'chapters': [{'number': '1', 'title': 'One', 'volume': '1'}],
            'collection': {'quarantined_groups': [{
                'display_key': '0', 'classification': 'explicit_reused_label',
            }]},
        })
        projection = build_publication_projection(
            [{'chapter': '0', 'title': ''}, {'chapter': '1', 'title': ''}],
            builder.build(), 'provider', 'provider',
        )
        self.assertEqual(('unmapped', 'reference_explicit'), tuple(
            row.mapping_state for row in projection.chapters
        ))

    def test_collection_reports_local_reused_label_quarantine_as_partial(self):
        resolved = WikipediaPublicationAdapter(
            WikipediaFixture(reused_label_pages())
        ).resolve_publication(match())
        metadata = resolved['collection'].metadata()
        self.assertEqual(('valid_partial', ['1'], 3, 1, 2), (
            resolved['status'], [row.number for row in resolved['chapters']],
            metadata['raw_publication_records'], metadata['safe_aggregated_records'],
            metadata['quarantined_records'],
        ))
        self.assertEqual('explicit_reused_label',
                         metadata['quarantined_groups'][0]['classification'])

    def test_quarantine_diagnostics_hydrate_identically_from_collection_cache(self):
        class NoBookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker', '', '', 'no_match', 'fixture')

        with tempfile.TemporaryDirectory() as folder:
            cache = SearchMetadataCache(Path(folder) / 'cache.sqlite3')
            first_fixture = WikipediaFixture(reused_label_pages())
            first = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(first_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            warm_fixture = WikipediaFixture(reused_label_pages())
            warm = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(warm_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            cache.close()
            self.assertEqual('hit', warm['cache_state'])
            self.assertEqual([], warm_fixture.calls)
            self.assertEqual(first['collection']['quarantined_groups'],
                             warm['collection']['quarantined_groups'])

    def test_uncollected_rows_hydrate_identically_from_warm_collection_cache(self):
        class NoBookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker', '', '', 'no_match', 'fixture')

        pages = collection_pages(segment_two=(
            graphic('2', (('3', 'Three'),)) +
            '\n==Chapters not yet published in volume format==\n* 4. Four\n'
        ))
        with tempfile.TemporaryDirectory() as folder:
            cache = SearchMetadataCache(Path(folder) / 'cache.sqlite3')
            first = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(WikipediaFixture(pages)), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            warm_fixture = WikipediaFixture(pages)
            warm = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(warm_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            cache.close()
        self.assertEqual('hit', warm['cache_state'])
        self.assertEqual([], warm_fixture.calls)
        def semantic(rows):
            return [(row['number'], row['title'], row['volume'], row['kind']) for row in rows]
        self.assertEqual(semantic(first['chapters']), semantic(warm['chapters']))
        self.assertEqual('uncollected', warm['chapters'][-1]['kind'])

    def test_segment_revision_cache_reuses_normalized_rows(self):
        cache = {}
        first_fixture = WikipediaFixture(collection_pages())
        first_adapter = WikipediaPublicationAdapter(first_fixture)
        first = first_adapter.resolve_publication(match(), cache.get, cache.__setitem__)
        second_fixture = WikipediaFixture(collection_pages())
        second_adapter = WikipediaPublicationAdapter(second_fixture)
        second = second_adapter.resolve_publication(match(), cache.get, cache.__setitem__)
        self.assertEqual(
            [(row.number, row.title, row.volume) for row in first['chapters']],
            [(row.number, row.title, row.volume) for row in second['chapters']],
        )
        self.assertEqual(2, second['collection'].segment_cache_hits)

        changed_pages = collection_pages()
        old = changed_pages['List of Test chapters (3–4)']
        changed_pages['List of Test chapters (3–4)'] = (old[0], 204, old[2])
        changed_adapter = WikipediaPublicationAdapter(WikipediaFixture(changed_pages))
        changed = changed_adapter.resolve_publication(match(), cache.get, cache.__setitem__)
        self.assertEqual(1, changed['collection'].segment_cache_hits)
        self.assertNotEqual(
            second['collection'].segments[1].revision_id,
            changed['collection'].segments[1].revision_id,
        )

    def test_collection_cache_is_warm_and_last_known_good_survives_segment_429(self):
        now = [0.0]

        class NoBookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker', '', '', 'no_match', 'fixture')

        with tempfile.TemporaryDirectory() as folder:
            cache = SearchMetadataCache(Path(folder) / 'cache.sqlite3', clock=lambda: now[0])
            first_fixture = WikipediaFixture(collection_pages())
            first = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(first_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            warm_fixture = WikipediaFixture(collection_pages())
            warm = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(warm_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            self.assertEqual((4, 0, 'hit'), (
                len(first['chapters']), len(warm_fixture.calls), warm['cache_state'],
            ))
            now[0] = IDENTITY_TTL + 1
            failing_fixture = WikipediaFixture(collection_pages())
            failing_fixture.failure = 'List of Test chapters (3–4)'
            stale = ReferenceMetadataService(
                cache, WikipediaPublicationAdapter(failing_fixture), NoBookwalker()
            ).lookup('test', {'title': 'Test', 'edition': 'original'})['wikipedia']
            self.assertEqual(('last_known_good', 4), (
                stale['cache_state'], len(stale['chapters']),
            ))
            self.assertIn('429', stale['refresh_error'])
            cache.close()

    def test_segment_429_without_last_known_good_is_failure_not_partial(self):
        class NoBookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker', '', '', 'no_match', 'fixture')

        fixture = WikipediaFixture(collection_pages())
        fixture.failure = 'List of Test chapters (3–4)'
        result = ReferenceMetadataService(
            None, WikipediaPublicationAdapter(fixture), NoBookwalker()
        ).lookup('test', {'title': 'Test', 'edition': 'original'})
        self.assertEqual('rate_limited', result['wikipedia']['status'])
        self.assertEqual([], result['wikipedia']['chapters'])
        self.assertIn('429', result['errors']['wikipedia'])

    def test_collection_rows_flow_through_manifest_projection_and_exact_covers(self):
        resolved = WikipediaPublicationAdapter(
            WikipediaFixture(collection_pages())
        ).resolve_publication(match())
        wiki = {
            'status': resolved['status'],
            'chapters': [row.__dict__ for row in resolved['chapters']],
            'volumes': [row.__dict__ for row in resolved['volumes']],
        }
        builder = PublicationManifestBuilder(
            {'canonical_identity': 'test', 'title': 'Test'}, 'original'
        ).apply_wikipedia(wiki)
        builder.apply_bookwalker({
            'match': {
                'publication_id': 'series/test', 'edition_id': 'series/test',
                'edition': 'original',
            },
            'covers': [{
                'url': 'https://covers/1.jpg', 'artwork_type': 'volume',
                'volume': '1', 'confidence': 'exact', 'edition_id': 'series/test',
                'volume_id': 'volume-1',
            }],
        })
        projection = build_publication_projection(
            [{'chapter': str(number), 'title': ''} for number in range(1, 6)],
            builder.build(), 'provider', 'provider',
        )
        self.assertEqual((4, 1), (
            projection.coverage['reference_explicit'],
            projection.coverage['unmapped_provider_chapters'],
        ))
        self.assertIsNotNone(projection.chapters[0].resolved_cover)
        self.assertIsNone(projection.chapters[4].resolved_cover)


if __name__ == '__main__':
    unittest.main()
