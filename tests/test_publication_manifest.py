import unittest
from pathlib import Path

from publication_manifest import (
    MANIFEST_SCHEMA_VERSION, PublicationManifestBuilder, build_publication_projection,
    project_inventory_through_manifest,
)


def work(title='Attack on Titan'):
    return {'canonical_identity': title.casefold(), 'title': title,
            'aliases': ('Shingeki no Kyojin',), 'creator': 'Hajime Isayama'}


def wiki_rows(count=3):
    return {
        'status': 'valid_with_data', 'cache_contract': 'wikipedia-structure-v2',
        'parser_version': '2', 'structure_page': 'List of Attack on Titan chapters',
        'match': {'publication_id': '123', 'confidence': 'confident'},
        'chapters': [
            {'number': str(index), 'title': 'Title %s' % index,
             'volume': str((index - 1) // 5 + 1), 'kind': 'chapter',
             'source_page': 'List of Attack on Titan chapters', 'confidence': 'explicit'}
            for index in range(1, count + 1)
        ],
    }


def bookwalker():
    return {
        'match': {'publication_id': 'series/4214', 'edition_id': 'series/4214',
                  'edition': 'original'},
        'covers': [{'url': 'https://covers/1.jpg', 'artwork_type': 'volume',
                    'volume': '1', 'confidence': 'exact',
                    'edition_id': 'series/4214', 'volume_id': 'uuid-1'}],
        'edition_artwork': [{'url': 'https://covers/edition.jpg', 'artwork_type': 'edition',
                             'confidence': 'exact', 'edition_id': 'series/4214'}],
        'description': 'Japanese candidate',
    }


class PublicationManifestTests(unittest.TestCase):
    def test_schema_work_chapter_volume_and_source_state(self):
        manifest = PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows()).apply_bookwalker(bookwalker()).build('en')
        self.assertEqual(MANIFEST_SCHEMA_VERSION, manifest.schema_version)
        self.assertEqual('attack on titan', manifest.work.canonical_identity)
        self.assertEqual(('wikipedia', 'explicit'),
                         (manifest.chapter('01').title.source, manifest.chapter('1').volume.confidence))
        self.assertEqual(('bookwalker', 'uuid-1'),
                         (manifest.volume('1').cover.source, manifest.volume(1).cover.volume_id))
        self.assertEqual('wikipedia',manifest.volume('1').provenance.source)
        self.assertEqual({'wikipedia', 'bookwalker'}, {state.source for state in manifest.source_states})

    def test_projection_normalizes_01_preserves_source_and_derives_zero_to_volume_one(self):
        manifest = PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows(2)).build()
        provider = (
            {'id': 'p0', 'chapter': '00', 'title': 'Chapter 00', '_source_id': 'mangapill'},
            {'id': 'p1', 'chapter': '01', 'title': 'Chapter 01', '_source_id': 'mangapill'},
        )
        projected, coverage = project_inventory_through_manifest(provider, manifest)
        self.assertEqual('Chapter 00', projected[0]['title'])
        self.assertEqual(('1','pre_chapter_one','derived_pre_chapter_one'),(
            projected[0]['volume'],projected[0]['_volume_source'],projected[0]['_projection_state'],
        ))
        self.assertEqual(('Title 1', '1', 'mangapill'),
                         (projected[1]['title'], projected[1]['volume'], projected[1]['_source_id']))
        self.assertEqual((2, 1, 0), (coverage['chapters_matched'],coverage['derived_pre_chapter_one'],coverage['unmapped_provider_chapters']))

    def test_provider_explicit_metadata_remains_authoritative(self):
        builder = PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows(1))
        manifest = builder.apply_provider_inventory((
            {'id': 'p1', 'chapter': '1', 'title': 'Provider Title', 'volume': '9'},
        ), 'mangadex').build()
        projected, _coverage = project_inventory_through_manifest((
            {'id': 'p1', 'chapter': '001', 'title': 'Provider Title', 'volume': '9',
             'source_id': 'mangadex'},
        ), manifest)
        self.assertEqual(('Provider Title', '9', 'mangadex'),
                         (projected[0]['title'], projected[0]['volume'], projected[0]['source_id']))
        self.assertEqual('mangadex', manifest.chapter('1').volume.source)

    def test_missing_provider_fields_receive_manifest_values_and_unmapped_survives(self):
        manifest = PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows(1)).build()
        projected, coverage = project_inventory_through_manifest((
            {'id': 'p1', 'chapter': '1', 'title': ''},
            {'id': 'p8', 'chapter': '8', 'title': ''},
        ), manifest)
        self.assertEqual(('Title 1', '1'), (projected[0]['title'], projected[0]['volume']))
        self.assertEqual('p8', projected[1]['id'])
        self.assertEqual(1, coverage['unmapped_provider_chapters'])

    def test_duplicate_acquisition_keys_block_reference_projection_only_locally(self):
        manifest=PublicationManifestBuilder(work(),'original').apply_wikipedia(wiki_rows(3)).build()
        projection=build_publication_projection((
            {'id':'a','chapter':'1','title':''},
            {'id':'b','chapter':'1','title':''},
            {'id':'c','chapter':'2','title':''},
            {'id':'d','chapter':'3','title':''},
        ),manifest)
        self.assertEqual(['unmapped','unmapped','reference_explicit','reference_explicit'],
                         [row.mapping_state for row in projection.chapters])
        self.assertTrue(all(not row.resolved_title.present for row in projection.chapters[:2]))
        self.assertEqual(('Title 2','Title 3'),tuple(
            row.resolved_title.value for row in projection.chapters[2:]
        ))

    def test_transient_failures_and_empty_updates_retain_last_known_good(self):
        current = PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows(3)).apply_bookwalker(bookwalker()).build()
        candidate = (PublicationManifestBuilder(work(), 'original', current)
                     .apply_wikipedia({'status': 'transient_failure', 'chapters': []})
                     .apply_bookwalker({'status': 'transient_failure'})
                     .build())
        self.assertEqual(3, len(candidate.chapters))
        self.assertEqual('https://covers/1.jpg', candidate.volume('1').cover.url)
        states = {state.source: state.status for state in candidate.source_states}
        self.assertEqual('transient_failure', states['wikipedia'])
        self.assertEqual('transient_failure', states['bookwalker'])

    def test_descriptions_coexist_and_explicit_language_beats_unknown_priority(self):
        builder = PublicationManifestBuilder(work(), 'original').apply_bookwalker(bookwalker())
        builder.apply_enrichment({
            'work_description_candidates': [
                {'value': 'English candidate', 'source': 'anilist', 'language': 'en',
                 'source_identity': '16498'}
            ]
        })
        manifest = builder.build('en')
        self.assertEqual(2, len(manifest.display.descriptions))
        self.assertEqual(('English candidate', 'anilist'),
                         (manifest.display.description.value, manifest.display.description.source))

    def test_bookwalker_description_is_evidence_but_never_display_authority(self):
        builder=PublicationManifestBuilder(work(),'original')
        builder.add_description('Readable provider Description','provider')
        builder.apply_bookwalker(bookwalker())
        manifest=builder.build('en')
        self.assertEqual(2,len(manifest.display.descriptions))
        self.assertEqual(('Readable provider Description','provider'),
                         (manifest.display.description.value,manifest.display.description.source))
        book_only=PublicationManifestBuilder(work(),'original').apply_bookwalker(bookwalker()).build('en')
        self.assertFalse(book_only.display.description.present)

    def test_enrichment_source_state_is_retained_without_second_fetch_path(self):
        manifest=PublicationManifestBuilder(work(),'original').apply_enrichment({
            'external_ids':{'anilist_id':'16498','kitsu_id':'7442'},
            'consensus_rating':8.7,'work_tags':['Action'],
        }).build()
        self.assertEqual({'anilist':'16498','kitsu':'7442'},
                         {row.source:row.source_identity for row in manifest.source_states})

    def test_attack_projection_139_of_144_and_one_piece_unsupported(self):
        inventory = tuple({'id': str(index), 'chapter': str(index), 'title': ''}
                          for index in range(0, 144))
        attack = (PublicationManifestBuilder(work(), 'original')
                  .apply_provider_inventory(inventory,'mangapill')
                  .apply_wikipedia(wiki_rows(139)).build())
        _rows, coverage = project_inventory_through_manifest(inventory, attack)
        self.assertEqual((140, 1, 4), (coverage['chapters_matched'],coverage['derived_pre_chapter_one'],coverage['unmapped_provider_chapters']))
        one_piece = PublicationManifestBuilder(
            {'canonical_identity': 'one piece', 'title': 'One Piece'}, 'original'
        ).apply_wikipedia({'status': 'unsupported_layout', 'chapters': []}).build()
        projected, coverage = project_inventory_through_manifest(({'id': '1100', 'chapter': '1100'},), one_piece)
        self.assertEqual((1, 0, 1), (len(projected), coverage['chapters_matched'], coverage['unmapped_provider_chapters']))

    def test_attack_accounting_resolves_144_with_distinct_derived_categories(self):
        inventory=(
            tuple({'chapter':str(number)} for number in range(1,140)) +
            ({'chapter':'0'}, {'chapter':'8.5'}, {'chapter':'34.5'},
             {'chapter':'70.5'}, {'chapter':'139.5'})
        )
        manifest=(PublicationManifestBuilder(work(),'original')
                  .apply_wikipedia(wiki_rows(139)).build())
        projection=build_publication_projection(inventory,manifest)
        coverage=projection.coverage
        self.assertEqual((144,139,4,1,0),(
            coverage['resolved_chapters'],coverage['reference_explicit'],
            coverage['derived_fractional'],coverage['derived_pre_chapter_one'],
            coverage['unmapped_provider_chapters'],
        ))
        self.assertEqual(len(inventory),sum(coverage[key] for key in (
            'provider_explicit','reference_explicit','derived_fractional',
            'derived_pre_chapter_one','unmapped_provider_chapters',
        )))

    def test_death_note_fill_and_jojolion_provider_non_regression(self):
        death = PublicationManifestBuilder({'canonical_identity': 'death note', 'title': 'Death Note'}, 'original').apply_wikipedia({
            **wiki_rows(1), 'chapters': [{'number': '1', 'title': 'Boredom', 'volume': '1',
                                          'kind': 'chapter', 'confidence': 'explicit'}],
        }).build()
        death_rows, _ = project_inventory_through_manifest(({'id': '1', 'chapter': '01', 'title': ''},), death)
        self.assertEqual(('Boredom', '1'), (death_rows[0]['title'], death_rows[0]['volume']))
        jojo = (PublicationManifestBuilder({'canonical_identity': 'jojolion', 'title': 'JoJolion'}, 'original')
                .apply_provider_inventory(({'id': '12.5', 'chapter': '12.5', 'title': 'Provider Decimal', 'volume': '3'},), 'mangadex')
                .apply_wikipedia({'status': 'valid_with_data', 'chapters': [
                    {'number': '12.5', 'title': 'Reference Decimal', 'volume': '4',
                     'kind': 'chapter', 'confidence': 'explicit'}]})
                .build())
        self.assertEqual(('Provider Decimal', '3'),
                         (jojo.chapter('12.5').title.value, jojo.chapter('12.5').volume.value))

    def test_runtime_resolves_reference_once_and_reuses_manifest_for_inventory(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        loaded=source[source.index('def _apply_loaded_manga'):source.index('def _apply_chapter_plan')]
        chapter=source[source.index('def _apply_chapter_plan'):source.index('def _on_volume_plan_failed')]
        self.assertEqual(1,loaded.count('self._start_reference_lookup()'))
        self.assertNotIn('self._start_reference_lookup()',chapter)
        self.assertIn('_try_finalize_chapter_projection',chapter)

    def test_fractional_parent_affinity_and_cover_resolution(self):
        volume_six=bookwalker(); volume_six['covers'][0]['volume']='6'
        manifest=(PublicationManifestBuilder(work(),'original')
                  .apply_provider_inventory(({'id':'34','chapter':'34','title':'Are You Stupid?','volume':'6'},),'mangapill')
                  .apply_bookwalker(volume_six).build())
        projection=build_publication_projection((
            {'id':'34','chapter':'34','title':'Are You Stupid?','volume':'6','_source_id':'mangapill'},
            {'id':'34.5','chapter':'34.5','title':'','_source_id':'mangapill'},
            {'id':'35','chapter':'35','title':'The Fight','volume':'7','_source_id':'mangapill'},
        ),manifest,selected_provider='mangadex')
        child=projection.chapters[1]
        self.assertEqual(('34.5','6','fractional_parent','derived','derived_fractional'),(
            child.canonical_key,child.effective_volume.value,child.effective_volume.source,
            child.effective_volume.confidence,child.mapping_state,
        ))
        self.assertFalse(child.resolved_title.present)
        self.assertEqual('https://covers/1.jpg',child.resolved_cover.url)
        self.assertEqual(('6','https://covers/1.jpg'),(
            projection.rows[1]['volume'],projection.rows[1]['_publication_cover_url'],
        ))
        self.assertEqual(('mangadex','mangapill'),
                         (child.selected_provider,child.acquisition_provider))
        self.assertEqual((2,1,0,2),(
            projection.coverage['provider_explicit'],projection.coverage['derived_fractional'],
            projection.coverage['unmapped_provider_chapters'],len(projection.chapters_for_volume('6')),
        ))

    def test_exact_volume_artwork_identity_survives_one_piece_boundary(self):
        one_piece=(PublicationManifestBuilder(
            {'canonical_identity':'one piece','title':'One Piece'},'original'
        ).apply_wikipedia({'status':'valid_complete','chapters':[
            {'number':'61','title':'Chapter 61','volume':'7','kind':'chapter','confidence':'explicit'},
            {'number':'62','title':'Chapter 62','volume':'7','kind':'chapter','confidence':'explicit'},
            {'number':'63','title':'Chapter 63','volume':'8','kind':'chapter','confidence':'explicit'},
            {'number':'64','title':'Chapter 64','volume':'8','kind':'chapter','confidence':'explicit'},
        ]}).apply_bookwalker({'match':{'publication_id':'one-piece','edition_id':'one-piece','edition':'original'},'covers':[
            {'url':'bookwalker://one-piece/7','artwork_type':'volume','volume':'7','confidence':'exact','edition_id':'one-piece','volume_id':'v7'},
            {'url':'bookwalker://one-piece/8','artwork_type':'volume','volume':'8','confidence':'exact','edition_id':'one-piece','volume_id':'v8'},
        ]}).build())
        rows=build_publication_projection(tuple(
            {'id':number,'chapter':number,'title':'','cover_url':'provider://series'}
            for number in ('61','62','63','64')
        ),one_piece).rows
        self.assertEqual(['7','7','8','8'],[row['volume'] for row in rows])
        self.assertEqual(rows[0]['_publication_cover_identity'],rows[1]['_publication_cover_identity'])
        self.assertEqual(rows[2]['_publication_cover_identity'],rows[3]['_publication_cover_identity'])
        self.assertNotEqual(rows[0]['_publication_cover_identity'],rows[2]['_publication_cover_identity'])
        self.assertEqual(['bookwalker://one-piece/7','bookwalker://one-piece/7',
                          'bookwalker://one-piece/8','bookwalker://one-piece/8'],
                         [row['_publication_cover_url'] for row in rows])

    def test_bleach_adjacent_volume_and_unknown_volume_do_not_alias_artwork(self):
        bleach=(PublicationManifestBuilder(
            {'canonical_identity':'bleach','title':'Bleach'},'original'
        ).apply_wikipedia({'status':'valid_complete','chapters':[
            {'number':'6','title':'','volume':'1','kind':'chapter','confidence':'explicit'},
            {'number':'7','title':'','volume':'2','kind':'chapter','confidence':'explicit'},
        ]}).apply_bookwalker({'match':{'publication_id':'bleach','edition_id':'bleach','edition':'original'},'covers':[
            {'url':'bookwalker://bleach/1','artwork_type':'volume','volume':'1','confidence':'exact','edition_id':'bleach','volume_id':'b1'},
            {'url':'bookwalker://bleach/2','artwork_type':'volume','volume':'2','confidence':'exact','edition_id':'bleach','volume_id':'b2'},
        ]}).build())
        rows=build_publication_projection((
            {'id':'6','chapter':'6','title':'','cover_url':'provider://series'},
            {'id':'7','chapter':'7','title':'','cover_url':'provider://series'},
            {'id':'unknown','chapter':'1155','title':'Known title','cover_url':'provider://series'},
        ),bleach).rows
        self.assertNotEqual(rows[0]['_publication_cover_identity'],rows[1]['_publication_cover_identity'])
        self.assertNotIn('_publication_cover_url',rows[2])
        self.assertNotIn('_publication_cover_identity',rows[2])

    def test_google_books_fills_only_existing_bookwalker_gaps(self):
        builder=(PublicationManifestBuilder(work(),'original')
                 .apply_wikipedia(wiki_rows(10)).apply_bookwalker(bookwalker()))
        builder.apply_google_books({'status':'valid','cache_contract':'google-books-artwork-v1','covers':[
            {'url':'google://volume-1','artwork_type':'volume','volume':'1','source':'google_books',
             'confidence':'exact','publication_id':'g-series','edition_id':'standard:en','volume_id':'g1'},
            {'url':'google://volume-2','artwork_type':'volume','volume':'2','source':'google_books',
             'confidence':'exact','publication_id':'g-series','edition_id':'standard:en','volume_id':'g2'},
            {'url':'google://volume-99','artwork_type':'volume','volume':'99','source':'google_books',
             'confidence':'exact','publication_id':'g-series','edition_id':'standard:en','volume_id':'g99'},
        ]})
        manifest=builder.build('en')
        self.assertEqual(('bookwalker','https://covers/1.jpg'),
                         (manifest.volume('1').cover.source,manifest.volume('1').cover.url))
        self.assertEqual(('google_books','google://volume-2','g2'),(
            manifest.volume('2').cover.source,manifest.volume('2').cover.url,
            manifest.volume('2').cover.volume_id,
        ))
        self.assertIsNone(manifest.volume('99'))

    def test_google_books_never_promotes_cover_to_no_volume_chapter(self):
        manifest=(PublicationManifestBuilder(work(),'original').apply_wikipedia(wiki_rows(2))
                  .apply_google_books({'status':'valid','covers':[
                      {'url':'google://2','artwork_type':'volume','volume':'2','source':'google_books',
                       'confidence':'exact','volume_id':'g2'}]}).build('en'))
        rows=build_publication_projection(({'id':'unknown','chapter':'1155','title':'Known'},),manifest).rows
        self.assertNotIn('_publication_cover_url',rows[0])

    def test_google_logical_identity_is_independent_of_preview_and_source_renditions(self):
        base={'status':'valid','cache_contract':'google-books-artwork-v1','covers':[
            {'url':'google://source-a','preview_url':'google://preview-a','source_url':'google://source-a',
             'source_field':'extraLarge','retrieval':'volumes_get_full','artwork_type':'volume','volume':'2',
             'source':'google_books','confidence':'exact','publication_id':'work|standard',
             'edition_id':'standard:en','volume_id':'google-v2'}]}
        first=(PublicationManifestBuilder(work(),'original').apply_wikipedia(wiki_rows(10))
               .apply_google_books(base).build('en'))
        changed={'status':'valid','covers':[dict(base['covers'][0],url='google://source-b',
                                                  preview_url='google://preview-b',source_url='google://source-b')]}
        second=(PublicationManifestBuilder(work(),'original').apply_wikipedia(wiki_rows(10))
                .apply_google_books(changed).build('en'))
        self.assertEqual(first.volume('2').cover.identity,second.volume('2').cover.identity)
        row=build_publication_projection(({'id':'6','chapter':'6'},),first).rows[0]
        self.assertEqual(('google://preview-a','google://source-a'),(
            row['_publication_cover_url'],row['_publication_source_cover_url'],
        ))

    def test_fractional_explicit_wins_and_unsafe_forms_remain_unmapped(self):
        manifest=(PublicationManifestBuilder(work(),'original')
                  .apply_provider_inventory(({'chapter':'34','volume':'6'},),'mangapill').build())
        projection=build_publication_projection((
            {'chapter':'34','volume':'6','_source_id':'mangapill'},
            {'chapter':'34.5','volume':'7','_source_id':'mangapill'},
            {'chapter':'35.5','_source_id':'mangapill'},
            {'chapter':'Special 34.5','_source_id':'mangapill'},
            {'chapter':'Extra 34.5','_source_id':'mangapill'},
            {'chapter':'34-35','_source_id':'mangapill'},
        ),manifest)
        self.assertEqual(('7','provider_explicit'),(
            projection.chapters[1].effective_volume.value,projection.chapters[1].mapping_state,
        ))
        self.assertEqual(['unmapped'] * 4,[row.mapping_state for row in projection.chapters[2:]])

    def test_pre_chapter_one_is_numeric_only_and_explicit_volume_wins(self):
        manifest=(PublicationManifestBuilder(work(),'original')
                  .apply_provider_inventory(({'chapter':'1','volume':'1'},),'mangapill')
                  .apply_bookwalker(bookwalker()).build())
        projection=build_publication_projection((
            {'chapter':'0','title':'Chapter Zero'},
            {'chapter':'0.5','title':''},
            {'chapter':'0.1','volume':'9'},
            {'chapter':'Prologue'},
            {'chapter':'Special'},
            {'chapter':'Extra'},
        ),manifest)
        self.assertEqual(['derived_pre_chapter_one','derived_pre_chapter_one','provider_explicit'],
                         [row.mapping_state for row in projection.chapters[:3]])
        self.assertEqual('9',projection.chapters[2].effective_volume.value)
        self.assertEqual(['unmapped'] * 3,[row.mapping_state for row in projection.chapters[3:]])
        self.assertEqual('Chapter Zero',projection.chapters[0].resolved_title.value)
        self.assertFalse(projection.chapters[1].resolved_title.present)
        self.assertEqual('https://covers/1.jpg',projection.chapters[1].resolved_cover.url)
        self.assertEqual(2,projection.coverage['derived_pre_chapter_one'])

    def test_projection_control_matrix_preserves_editions_and_composition(self):
        chainsaw_inventory=tuple(
            {'id':str(number),'chapter':str(number),'volume':str((number-1)//10+1) if number <= 97 else '',
             '_source_id':'mangadex' if number <= 97 else 'mangapill'}
            for number in range(1,233)
        )
        chainsaw_wiki=wiki_rows(232)
        chainsaw=(PublicationManifestBuilder({'canonical_identity':'chainsaw man','title':'Chainsaw Man'},'original')
                  .apply_provider_inventory(chainsaw_inventory,'provider')
                  .apply_wikipedia(chainsaw_wiki).build())
        projection=build_publication_projection(chainsaw_inventory,chainsaw,selected_provider='mangadex')
        self.assertEqual((232,97,135,0,('mangadex','mangapill')),(
            projection.coverage['resolved_chapters'],projection.coverage['provider_explicit'],
            projection.coverage['reference_explicit'],projection.coverage['unmapped_provider_chapters'],
            projection.acquisition_providers,
        ))

        punch_inventory=tuple({'chapter':str(number),'_source_id':'mangapill'}
                              for number in range(1,312)) + ({'chapter':'34.5','_source_id':'mangapill'},)
        punch=PublicationManifestBuilder(
            {'canonical_identity':'one-punch man','title':'One-Punch Man'},'original'
        ).apply_wikipedia(wiki_rows(194)).build()
        punch_projection=build_publication_projection(punch_inventory,punch)
        self.assertEqual((312,195,1,117),(
            len(punch_projection.chapters),punch_projection.coverage['resolved_chapters'],
            punch_projection.coverage['derived_fractional'],
            punch_projection.coverage['unmapped_provider_chapters'],
        ))

        standard=PublicationManifestBuilder(
            {'canonical_identity':'one piece','title':'One Piece'},'original'
        ).apply_wikipedia({'status':'unsupported_layout'}).build()
        color=PublicationManifestBuilder(
            {'canonical_identity':'one piece','title':'One Piece'},'color'
        ).apply_provider_inventory(({'chapter':'1','volume':'1'},),'mangadex').build()
        self.assertEqual((0,1,'original','color'),(
            build_publication_projection(({'chapter':'1'},),standard).coverage['resolved_chapters'],
            build_publication_projection(({'chapter':'1','volume':'1'},),color).coverage['resolved_chapters'],
            standard.edition.identity,color.edition.identity,
        ))


if __name__ == '__main__':
    unittest.main()
