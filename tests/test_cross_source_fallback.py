import unittest

from cross_source_fallback import (
    build_cross_source_plan, chapter_identities_match, chapter_identity,
)
from inventory_comparison import SourceInventory
from source_adapter import SourceAdapter
from source_registry import SourceRegistry


class FakeChapterSource(SourceAdapter):
    capabilities = frozenset({'chapters'})

    def __init__(self, source_id, name, chapters=(), failure=''):
        self.source_id = source_id
        self.display_name = name
        self.chapters = list(chapters)
        self.failure = failure

    def parse_manga_ref(self, value): return value
    def get_manga(self, value, preferred='en'): return {}
    def search(self, query, **kwargs): return {'rows': []}
    def get_download_plan(self, value, language, start_volume=None, end_volume=None): return {}
    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        if self.failure:
            raise RuntimeError(self.failure)
        return list(self.chapters)
    def get_volume_covers(self, value): return {}
    def get_page_manifest(self, chapter_id, retry_callback=None): return {}
    def fetch_binary(self, url, **kwargs): return b''
    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None): return b'', True


def chapter(number, *, title='', volume=None, source_id=''):
    return {'id': f'{source_id}-{number}-{title}', 'chapter': number,
            'title': title, 'volume': volume, 'pages': 1}


class CrossSourceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.dex = FakeChapterSource('mangadex', 'MangaDex')
        self.pill = FakeChapterSource('mangapill', 'MangaPill')
        self.weeb = FakeChapterSource('weebcentral', 'WeebCentral')
        self.registry = SourceRegistry((self.dex, self.pill, self.weeb))

    def inventory(self, source, *, edition='original', language='en', usable=True, error=''):
        return SourceInventory(source.source_id, source.display_name,
                               {'url': source.source_id + '-series'}, language, edition,
                               language_match=usable, chapter_count=len(source.chapters),
                               usable=usable, complete=usable and not error, error=error)

    def plan(self, workflow='chapter', primary=None, inventories=None):
        inventories = inventories or (self.inventory(self.dex), self.inventory(self.pill))
        return build_cross_source_plan(inventories, self.registry, primary=primary or inventories[0], workflow=workflow)

    def test_primary_complete_does_not_mix_duplicate_provider_content(self):
        self.dex.chapters = [chapter('1', source_id='dex'), chapter('2', source_id='dex')]
        self.pill.chapters = [chapter('Chapter 1', source_id='pill'), chapter('Ch. 2', source_id='pill')]
        plan = self.plan()
        self.assertEqual([item.source_id for item in plan.items], ['mangadex', 'mangadex'])
        self.assertFalse(plan.fallback_items)

    def test_one_missing_chapter_is_safely_filled(self):
        self.dex.chapters = [chapter('1', source_id='dex'), chapter('3', source_id='dex')]
        self.pill.chapters = [chapter('1', source_id='pill'), chapter('2', source_id='pill'), chapter('3', source_id='pill')]
        plan = self.plan()
        self.assertEqual([(item.canonical_identity.number, item.source_id) for item in plan.items],
                         [('1', 'mangadex'), ('2', 'mangapill'), ('3', 'mangadex')])
        self.assertEqual(plan.notice, '1 missing chapter will be filled from MangaPill.')
        self.assertEqual(plan.gaps[0].status, 'filled')

    def test_weebcentral_can_supply_a_safe_chapter_mode_fallback(self):
        self.dex.chapters=[chapter('1',source_id='dex'),chapter('3',source_id='dex')]
        self.weeb.chapters=[chapter('1',source_id='weeb'),chapter('2',source_id='weeb'),chapter('3',source_id='weeb')]
        dex=self.inventory(self.dex); weeb=self.inventory(self.weeb)
        plan=self.plan(primary=dex,inventories=(dex,weeb))
        self.assertEqual([(item.canonical_identity.number,item.source_id) for item in plan.items],[
            ('1','mangadex'),('2','weebcentral'),('3','mangadex')])

    def test_several_gaps_are_filled_deterministically(self):
        self.dex.chapters = [chapter('1', source_id='dex'), chapter('4', source_id='dex')]
        self.pill.chapters = [chapter(str(number), source_id='pill') for number in (1, 2, 3, 4)]
        first = self.plan(); second = self.plan()
        self.assertEqual(first, second)
        self.assertEqual([(item.canonical_identity.number, item.source_id) for item in first.items],
                         [('1', 'mangadex'), ('2', 'mangapill'), ('3', 'mangapill'), ('4', 'mangadex')])

    def test_ambiguous_special_is_never_used_as_fallback(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        self.pill.chapters = [chapter('1', source_id='pill'), chapter('Special', source_id='pill')]
        plan = self.plan()
        self.assertEqual(len(plan.items), 1)
        self.assertFalse(plan.gaps)

    def test_decimal_chapter_identity_aligns(self):
        self.assertTrue(chapter_identities_match(chapter_identity(chapter('Chapter 12.50')), chapter_identity(chapter('Ch. 12.5'))))
        self.assertFalse(chapter_identities_match(chapter_identity(chapter('12')), chapter_identity(chapter('12.5'))))

    def test_conflicting_title_is_not_used_as_fallback(self):
        self.dex.chapters = [chapter('12', title='The Beginning', source_id='dex')]
        self.pill.chapters = [chapter('12', title='A Different Chapter', source_id='pill')]
        plan = self.plan()
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.gaps[0].status, 'unresolved')

    def test_edition_mismatch_prevents_fallback(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        self.pill.chapters = [chapter('2', source_id='pill')]
        plan = self.plan(inventories=(self.inventory(self.dex), self.inventory(self.pill, edition='official_color')))
        self.assertEqual([item.source_id for item in plan.items], ['mangadex'])

    def test_language_mismatch_prevents_fallback(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        self.pill.chapters = [chapter('2', source_id='pill')]
        plan = self.plan(inventories=(self.inventory(self.dex), self.inventory(self.pill, language='fr')))
        self.assertEqual([item.source_id for item in plan.items], ['mangadex'])

    def test_colored_vs_bw_mismatch_prevents_fallback(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        self.pill.chapters = [chapter('2', source_id='pill')]
        plan = self.plan(inventories=(self.inventory(self.dex, edition='original'), self.inventory(self.pill, edition='fan_color')))
        self.assertFalse(plan.fallback_items)

    def test_provider_failure_uses_safe_compatible_fallback(self):
        self.dex.failure = 'MangaDex offline'
        self.pill.chapters = [chapter('1', source_id='pill'), chapter('2', source_id='pill')]
        primary = self.inventory(self.dex, usable=False, error='MangaDex offline')
        plan = self.plan(primary=primary, inventories=(primary, self.inventory(self.pill)))
        self.assertEqual([item.source_id for item in plan.items], ['mangapill', 'mangapill'])
        self.assertTrue(all(item.reason == 'primary-failure-fallback' for item in plan.items))

    def test_provider_failure_without_safe_fallback_leaves_empty_plan(self):
        self.dex.failure = 'MangaDex offline'
        self.pill.chapters = [chapter('1', source_id='pill')]
        primary = self.inventory(self.dex, usable=False, error='MangaDex offline')
        plan = self.plan(primary=primary, inventories=(primary, self.inventory(self.pill, edition='official_color')))
        self.assertFalse(plan.items)
        self.assertFalse(plan.can_execute)

    def test_provenance_is_retained_for_every_plan_item(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        self.pill.chapters = [chapter('2', source_id='pill')]
        plan = self.plan()
        fallback = plan.fallback_items[0]
        self.assertEqual(fallback.source_name, 'MangaPill')
        self.assertEqual(fallback.reference['id'], 'pill-2-')
        self.assertEqual(fallback.canonical_identity.number, '2')

    def test_single_provider_mangadex_remains_single_provider(self):
        self.dex.chapters = [chapter('1', source_id='dex')]
        plan = self.plan(inventories=(self.inventory(self.dex),))
        self.assertEqual([item.source_id for item in plan.items], ['mangadex'])

    def test_single_provider_mangapill_remains_single_provider(self):
        self.pill.chapters = [chapter('1', source_id='pill')]
        inventory = self.inventory(self.pill)
        plan = build_cross_source_plan((inventory,), self.registry, primary=inventory)
        self.assertEqual([item.source_id for item in plan.items], ['mangapill'])

    def test_volume_workflow_records_but_does_not_execute_mixed_provider_gap(self):
        self.dex.chapters = [chapter('1', volume=1, source_id='dex')]
        self.pill.chapters = [chapter('2', source_id='pill')]
        plan = self.plan(workflow='volume')
        self.assertEqual(plan.fallback_items[0].source_id, 'mangapill')
        self.assertFalse(plan.fallback_items[0].output_eligible)
        self.assertFalse(plan.can_execute)
        self.assertIn('not supported yet', plan.gaps[0].reason)


if __name__ == '__main__':
    unittest.main()
