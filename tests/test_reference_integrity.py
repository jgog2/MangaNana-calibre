"""Synthetic, no-network structural authority and source-integrity contracts."""
from copy import deepcopy
from dataclasses import replace
import unittest

from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import aggregate_mappings, MangaDexStructureResolver
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.metadata.reference_integration import WIKIPEDIA_CACHE_CONTRACT


WORK = 'fixture:reference-integrity'
MID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
RID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def aggregate(pairs):
    volumes = {}
    for index, pair in enumerate(pairs):
        chapter, volume, *ids = pair
        group = volumes.setdefault(str(volume), dict(volume=volume, chapters={}))
        group['chapters'][str(index)] = dict(chapter=chapter, **({'id': ids[0]} if ids else {}))
    return dict(result='ok', volumes=volumes)


def md(pairs=(('1', '1'), ('2', '1'), ('3', '2'))):
    mappings, ambiguous = aggregate_mappings(aggregate(pairs))
    return dict(status='valid' if mappings else 'no_structure', cache_contract='mangadex-structure-v1',
        canonical_work_id=WORK, edition_profile='standard', manga_id=MID,
        mappings=mappings, ambiguous_chapters=ambiguous, cache_state='refreshed')


def wiki(pairs=(('1', '1'), ('2', '1'), ('3', '2'))):
    return dict(status='valid_complete', cache_contract=WIKIPEDIA_CACHE_CONTRACT,
        cache_state='refreshed', match=dict(confidence='confident', title='Synthetic work', edition='standard'),
        chapters=[dict(number=k, volume=v, kind='chapter', confidence='explicit', source='wikipedia',
            source_page='Synthetic chapters', source_record_id='record:'+k, language='en') for k, v in pairs],
        volumes=[])


def builder(existing=None):
    return PublicationManifestBuilder(dict(canonical_identity=WORK, title='Synthetic work', language='en',
        publication_context=dict(shareable=True, canonical_work_id=WORK, canonical_title='Synthetic work')),
        'standard', existing=existing)


def project(m=None, w=None, rows=None, existing=None):
    b = builder(existing)
    rows = rows if rows is not None else [dict(id='reader:'+k, chapter=k) for k in ('1', '2', '3')]
    b.apply_provider_inventory(rows, 'mangapill')
    if m is not None: b.apply_mangadex_structure(m)
    if w is not None: b.apply_wikipedia(w)
    manifest = b.build('en')
    return manifest, build_publication_projection(rows, manifest, 'mangapill', 'mangapill')


class ReferenceIntegrity(unittest.TestCase):
    def test_mangadex_only_and_sparse_uncorroborated(self):
        for value in (md(), md((('2', '7'),))):
            with self.subTest(value=value):
                _, p = project(value)
                self.assertEqual(value['mappings']['2'], p.chapters[1].effective_volume.value)

    def test_wikipedia_only(self):
        _, p = project(w=wiki())
        self.assertEqual(['1', '1', '2'], [c.effective_volume.value for c in p.chapters])

    def test_agreement_retains_mangadex_precedence_and_claims(self):
        m, p = project(md(), wiki())
        self.assertEqual('mangadex_structure', p.chapters[1].effective_volume.source)
        self.assertEqual(2, len(m.runtime_publication['reference_claims']['2']))

    def test_direct_disagreement_only_quarantines_affected_chapter(self):
        rows = [dict(id='reader:'+k, chapter=k) for k in ('1', '2', '3')]
        saved = deepcopy(rows)
        m, p = project(md(), wiki((('1', '1'), ('2', '9'), ('3', '2'))), rows)
        self.assertEqual(['1', None, '2'], [c.effective_volume.value for c in p.chapters])
        self.assertIn('2', m.ambiguous_chapter_keys)
        self.assertEqual(['2'], m.runtime_publication['unresolved_reference_chapters'])
        self.assertEqual(2, len(m.runtime_publication['reference_conflicts'][0]['claims']))
        self.assertEqual(saved, rows)
        self.assertEqual(saved, [c.acquisition for c in p.chapters])

    def test_internal_mangadex_ambiguity_falls_back_to_wikipedia(self):
        _, p = project(md((('1', '1'), ('2', '1'), ('2.0', '2'), ('3', '2'))), wiki())
        self.assertEqual('wikipedia', p.chapters[1].effective_volume.source)
        self.assertEqual('1', p.chapters[1].effective_volume.value)

    def test_internal_mangadex_ambiguity_without_fallback(self):
        _, p = project(md((('2', '1'), ('2.0', '2'))))
        self.assertFalse(p.chapters[1].effective_volume.present)

    def test_invalid_or_stale_wikipedia_claim_cannot_challenge_mangadex(self):
        bad = wiki((('2', '9'),))
        variations = [dict(bad, cache_state='last_known_good'), dict(bad, status='transient_failure'),
            dict(bad, cache_contract='unknown'), dict(bad, match=dict(bad['match'], edition='omnibus')),
            dict(bad, match=dict(bad['match'], title='Other work')),
            dict(bad, chapters=[dict(bad['chapters'][0], language='ja')]),
            dict(bad, chapters=[dict(bad['chapters'][0], confidence='candidate')])]
        for value in variations:
            with self.subTest(value=value):
                m, p = project(md(), value)
                self.assertEqual('1', p.chapters[1].effective_volume.value)
                self.assertFalse(m.runtime_publication.get('unresolved_reference_chapters'))

    def test_incompatible_mangadex_uses_wikipedia(self):
        for extra in (dict(canonical_work_id='other'), dict(edition_profile='omnibus')):
            _, p = project(dict(md(), **extra), wiki())
            self.assertEqual('wikipedia', p.chapters[1].effective_volume.source)

    def test_internally_ambiguous_wikipedia_cannot_challenge_mangadex(self):
        _, p = project(md(), wiki((('2', '8'), ('2.0', '9'))))
        self.assertEqual('1', p.chapters[1].effective_volume.value)

    def test_stale_mangadex_does_not_outrank_eligible_current_wikipedia(self):
        _, p = project(dict(md(),cache_state='last_known_good',refresh_status='transient_failure'),
                       wiki((('2','9'),)))
        self.assertEqual(('9','wikipedia'), (p.chapters[1].effective_volume.value,p.chapters[1].effective_volume.source))

    def test_provider_authority_both_sides(self):
        for volume in ('1', '9'):
            rows = [dict(id='reader', chapter='2', volume=volume)]
            m, p = project(md(), wiki((('2', '9'),)), rows)
            self.assertEqual(volume, p.chapters[0].effective_volume.value)
            self.assertEqual('provider_explicit', p.chapters[0].mapping_state)
            self.assertEqual([], m.runtime_publication['unresolved_reference_chapters'])
            self.assertEqual('mangapill', m.runtime_publication['reference_conflicts'][0]['resolved_by'])

    def test_fractional_conflict_and_children_cannot_derive(self):
        pairs = (('1', '1'), ('2', '1'), ('2.5', '1'), ('3', '2'))
        rows = [dict(id=k, chapter=k) for k in ('1', '2', '2.1', '2.2', '2.5', '3')]
        m, p = project(md(pairs), wiki((('2', '9'), ('2.5', '9'))), rows)
        self.assertEqual(['1', None, None, None, None, '2'], [c.effective_volume.value for c in p.chapters])
        self.assertEqual(['2', '2.5'], m.runtime_publication['unresolved_reference_chapters'])

    def test_special_conflict_never_uses_parent(self):
        w = wiki((('2.5', '9'),))
        w['chapters'][0]['kind'] = 'special'
        _, p = project(md((('2', '1'), ('2.5', '1'))), w,
            [dict(id=k, chapter=k) for k in ('2', '2.5')])
        self.assertFalse(p.chapters[1].effective_volume.present)

    def test_internal_fractional_ambiguity_blocks_derivation_but_allows_wiki(self):
        value = md((('2','1'), ('2.5','1'), ('2.50','2')))
        rows = [dict(id=k, chapter=k) for k in ('2','2.5')]
        _, p = project(value, rows=rows)
        self.assertFalse(p.chapters[1].effective_volume.present)
        _, p = project(value, wiki((('2.5','9'),)), rows)
        self.assertEqual('9', p.chapters[1].effective_volume.value)

    def test_ineligible_future_wikipedia_membership_cannot_challenge(self):
        w = wiki((('2','9'),))
        w['volumes'] = [dict(number='9', release_status='preorder')]
        _, p = project(md(), w)
        self.assertEqual('1', p.chapters[1].effective_volume.value)

    def test_refresh_removes_old_mapping_without_mutating_old_manifest(self):
        old, _ = project(md(), wiki())
        new, p = project(md(), wiki((('2', '9'),)), existing=old)
        self.assertEqual('1', old.chapter('2').volume.value)
        self.assertFalse(new.chapter('2').volume.present)
        self.assertFalse(p.chapters[1].effective_volume.present)
        recovered, p = project(md(), wiki(), existing=new)
        self.assertEqual('1', p.chapters[1].effective_volume.value)
        self.assertNotIn('2', recovered.ambiguous_chapter_keys)

    def test_repeated_build_and_reverse_application_order(self):
        for reverse in (False, True):
            b = builder()
            if reverse: b.apply_wikipedia(wiki((('2', '9'),)))
            b.apply_mangadex_structure(md())
            if not reverse: b.apply_wikipedia(wiki((('2', '9'),)))
            for _ in range(2): self.assertFalse(b.build().chapter('2').volume.present)

    def test_partial_wikipedia_refresh_challenges_previous_eligible_mangadex(self):
        old, _ = project(md(), wiki())
        b = builder(old).apply_wikipedia(wiki((('2', '9'),)))
        self.assertFalse(b.build().chapter('2').volume.present)
        self.assertEqual('1', old.chapter('2').volume.value)

    def test_invalid_refresh_removes_previous_mangadex_and_can_use_wikipedia(self):
        old, _ = project(md(), wiki())
        for status in ('invalid_structure', 'no_structure'):
            b = builder(old).apply_mangadex_structure(dict(md(), status=status, mappings={}))
            self.assertFalse(b.build().chapter('2').volume.present)
            b.apply_wikipedia(wiki())
            self.assertEqual('wikipedia', b.build().chapter('2').volume.source)

    def test_explicit_wikipedia_range_can_challenge(self):
        w = wiki()
        w['chapters'] = [dict(w['chapters'][0], number='1-2', kind='range', volume='9')]
        m, _ = project(md(), w)
        self.assertEqual(['1', '2'], m.runtime_publication['unresolved_reference_chapters'])

    def test_verified_and_reviewed_shared_curation_authority(self):
        for verification in ('VERIFIED', 'REVIEWED'):
            b = builder().apply_mangadex_structure(md()).apply_wikipedia(wiki((('2', '9'),)))
            automatic = b.build()
            b.apply_curated(dict(status='matched', identity=dict(trusted=True, canonical_work_id=WORK,
                edition='standard', language='en'), fields=[dict(entity='chapter', record_key='2',
                field='volume', value='9', verification=verification)]))
            effective = b.build()
            p = build_publication_projection([dict(id='reader', chapter='2')], effective)
            self.assertFalse(automatic.chapter('2').volume.present)
            self.assertEqual(('9', 'curated_database'),
                (p.chapters[0].effective_volume.value, p.chapters[0].effective_volume.source))


class AggregateIntegrity(unittest.TestCase):
    def test_equivalent_and_conflicting_normalized_labels(self):
        self.assertEqual(({'10': '1'}, []), aggregate_mappings(aggregate((('10', '01'), ('10.0', '1')))))
        self.assertEqual(({}, ['10']), aggregate_mappings(aggregate((('10', '1'), ('10.0', '2')))))

    def test_missing_membership_is_not_contradiction(self):
        self.assertEqual(({'10': '1'}, []), aggregate_mappings(aggregate((('10', '1'), ('10', None)))))

    def test_zero_decimal_sparse_nonmonotonic_remain_supported(self):
        value = aggregate((('0', '0'), ('0.5', '0.5'), ('232', '1'), ('203', '20')))
        self.assertEqual({'0':'0', '0.5':'0.5', '203':'20', '232':'1'}, aggregate_mappings(value)[0])

    def test_conflicting_reuse_of_release_identifier_quarantines_all_claims(self):
        value = aggregate((('10', '1', RID), ('11', '2', RID), ('12', '2')))
        mappings, ambiguous, diagnostics = aggregate_mappings(value, with_diagnostics=True)
        self.assertEqual({'12':'2'}, mappings)
        self.assertEqual(['10', '11'], ambiguous)
        self.assertTrue(any(d['reason']=='conflicting_release_identifier' for d in diagnostics))

    def test_repeated_release_identifier_same_claim_and_absent_volume(self):
        value = aggregate((('10', '1', RID), ('10.0', '1.0', RID), ('10', None, RID)))
        self.assertEqual(({'10':'1'}, []), aggregate_mappings(value))

    def test_malformed_record_has_diagnostics(self):
        with self.assertRaises(ValueError) as caught:
            aggregate_mappings(dict(result='ok', volumes={'1':dict(volume='1', chapters=[17])}))
        self.assertTrue(caught.exception.diagnostics)

    def test_identifier_in_others_conflicts_with_primary_release(self):
        value = aggregate((('10','1',RID), ('11','2')))
        value['volumes']['2']['chapters']['1']['others'] = [RID]
        self.assertEqual(({}, ['10','11']), aggregate_mappings(value))

    def test_legacy_unvalidated_cache_is_not_used_on_network_failure(self):
        from calibre_plugins.manganana.discovery.search_cache import CacheHit
        from unittest.mock import Mock
        old = md((('10','1'),))
        cache = Mock()
        cache.get_reference_structure.return_value = CacheHit(old,0,False)
        cache.get.return_value = CacheHit(old,0,True)
        def fail(url): raise OSError('offline')
        r = MangaDexStructureResolver(cache, fail).lookup(dict(canonical_work_id=WORK,
            identity_confidence='high',edition_profile='standard',media_type='manga',mangadex_title_ids=[MID]))
        self.assertEqual('transient_failure',r['status'])
        self.assertFalse(r['mappings'])

    def test_malformed_refresh_cannot_resurrect_previous_mapping(self):
        from calibre_plugins.manganana.discovery.search_cache import CacheHit
        from unittest.mock import Mock
        cache = Mock()
        value = MangaDexStructureResolver(request_json=lambda u:aggregate((('10','1'),))).lookup(
            dict(canonical_work_id=WORK, identity_confidence='high', edition_profile='standard',
                 media_type='manga', mangadex_title_ids=[MID]))
        cache.get_reference_structure.return_value = None
        cache.get.return_value = CacheHit(value, 0, True)
        r = MangaDexStructureResolver(cache, lambda u:dict(result='ok', volumes={'1':{}})).lookup(
            dict(canonical_work_id=WORK, identity_confidence='high', edition_profile='standard',
                 media_type='manga', mangadex_title_ids=[MID]))
        self.assertEqual('invalid_structure', r['status'])
        self.assertFalse(r['mappings'])

    def test_bad_refresh_replaces_cache_so_later_network_failure_cannot_resurrect_it(self):
        import tempfile
        from pathlib import Path
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, IDENTITY_TTL
        now = [100.0]
        evidence = dict(canonical_work_id=WORK,identity_confidence='high',edition_profile='standard',
                        media_type='manga',mangadex_title_ids=[MID])
        with tempfile.TemporaryDirectory() as folder:
            cache = SearchMetadataCache(Path(folder)/'cache.db',clock=lambda:now[0])
            try:
                good = MangaDexStructureResolver(cache,lambda u:aggregate((('10','1'),))).lookup(evidence)
                self.assertEqual({'10':'1'},good['mappings'])
                now[0] += IDENTITY_TTL+1
                bad = MangaDexStructureResolver(cache,lambda u:dict(result='ok',volumes={'1':{}})).lookup(evidence)
                self.assertEqual('invalid_structure',bad['status'])
                def fail(url): raise OSError('offline')
                later = MangaDexStructureResolver(cache,fail).lookup(evidence)
                self.assertEqual('transient_failure',later['status'])
                self.assertFalse(later['mappings'])
            finally: cache.close()


if __name__ == '__main__': unittest.main()
