"""Listing size and grouping must never masquerade as full-work completeness."""
import copy
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest

from calibre_plugins.manganana.publication.inventory_coverage import describe_inventory, entry_text
from calibre_plugins.manganana.publication.publication_manifest import FieldEvidence
from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource

ROOT = Path(__file__).resolve().parents[1]


def reference(key, volume, source='wikipedia', status='valid'):
    return SimpleNamespace(key=key, volume=FieldEvidence(volume, source, 'explicit', status=status))


class CoverageTests(unittest.TestCase):
    def facts(self, rows=(), **kwargs):
        values = dict(state='ready', provider_id='weebcentral', provider_name='WeebCentral', language='English', rows=rows)
        values.update(kwargs)
        return describe_inventory(**values)

    def test_counts_records_not_highest_number(self):
        result = self.facts([dict(id='a', chapter='1'), dict(id='b', chapter='999')])
        self.assertEqual(2, result.source_entries)
        self.assertIn('2 chapter entries', result.summary)
        self.assertIn('Full-work coverage unverified', result.status)

    def test_all_grouped_does_not_mean_complete_volume_or_work(self):
        result = self.facts([dict(id='a', chapter='17', volume=3)])
        self.assertEqual((('3', 1),), result.groups)
        self.assertFalse(result.ungrouped)
        self.assertIn('unverified', result.status)

    def test_unknown_mapping_is_not_a_missing_download(self):
        rows = [dict(id='prologue', chapter='Prologue 1', numbering_group='prologue')]
        result = self.facts(rows)
        self.assertEqual(1, result.source_entries)
        self.assertEqual(1, len(result.ungrouped))
        self.assertIn('not grouped into volumes', result.status)
        self.assertNotIn('missing', result.status.lower())

    def test_references_are_review_hints_not_complete_catalog(self):
        manifest = SimpleNamespace(chapters=[reference('1', 1), reference('2', 2)])
        result = self.facts([dict(id='a', volume=2)], manifest=manifest)
        self.assertEqual(('1',), result.reference_gaps)
        self.assertIn('Reference gaps to review', result.status)
        self.assertIn('Full-work coverage unverified', result.status)

    def test_reference_number_matches_do_not_prove_chapter_coverage(self):
        manifest = SimpleNamespace(chapters=[reference('1', 1), reference('2', 1)])
        result = self.facts([dict(id='a', chapter='1', volume=1)], manifest=manifest)
        self.assertFalse(result.reference_gaps)
        self.assertIn('unverified', result.status)

    def test_cover_catalog_is_not_chapter_membership(self):
        manifest = SimpleNamespace(chapters=[reference('1', 1, 'bookwalker')], volumes=[dict(key='1')])
        self.assertFalse(self.facts(manifest=manifest).reference_volumes)

    def test_ambiguous_invalid_and_stale_reference_claims_are_not_counted(self):
        manifest = SimpleNamespace(chapters=[reference('1', 1), reference('2', 2, status='invalid'),
            reference('3', 3, status='valid_stale')], ambiguous_chapter_keys=['1'])
        self.assertFalse(self.facts(manifest=manifest).reference_volumes)

    def test_pending_and_failed_never_show_previous_counts(self):
        for state in ('loading', 'error'):
            result = self.facts([dict(id='old', volume=1)], state=state)
            self.assertEqual(0, result.source_entries)
            self.assertFalse(result.groups)
            self.assertNotIn('0 chapter entries', result.summary)
        self.assertIn('loading failure', self.facts(state='error').status)

    def test_empty_is_distinct_from_loading(self):
        self.assertIn('No downloadable entries found', self.facts(state='empty').status)
        self.assertEqual(0, self.facts([dict(id='old')],state='empty').source_entries)
        self.assertIn('loading', self.facts(state='loading').status)

    def test_metadata_counts_never_replace_actual_acquisition_rows(self):
        result = self.facts([dict(id='a', volume=1)], plan={'chapters_by_volume':{1:999}, 'bonus_chapters':30})
        self.assertEqual(1, result.source_entries)
        self.assertEqual((('1', 1),), result.groups)

    def test_prepared_groups_preserve_other_provider_attribution(self):
        plan = {'volume_groups':[{'kind':'volume','volume':1,'chapters':[
            dict(id='a', _source_id='weebcentral'), dict(id='b', _source_id='mangadex')]}]}
        result = self.facts(plan=plan)
        self.assertEqual((1, 1), (result.source_entries, result.other_entries))
        self.assertIn('entries from other sources', result.summary)

    def test_packaged_volume_files_are_not_chapter_counts(self):
        result = self.facts([dict(id='a', volume=1, _unit_kind='volume')])
        self.assertTrue(result.packaged)
        self.assertIn('1 volume file', result.summary)
        self.assertNotIn('chapter entry', result.summary)

    def test_mixed_acquisition_types_are_not_all_called_chapters(self):
        result = self.facts([dict(id='a', volume=1, _unit_kind='volume'), dict(id='b', volume=1)])
        self.assertTrue(result.mixed_units)
        self.assertIn('2 source entries', result.summary)

    def test_invalid_volume_numbers_are_not_grouped(self):
        result = self.facts([dict(id=str(v), volume=v) for v in ('NaN', 'Infinity', '-2', 'other')])
        self.assertFalse(result.groups)
        self.assertEqual(4, len(result.ungrouped))

    def test_inputs_are_unchanged(self):
        rows=[dict(id='a', volume=1), dict(id='b', chapter='special')]
        plan={'volume_groups':[dict(kind='volume',volume=1,chapters=rows[:1]),dict(kind='standalone',chapters=rows[1:])]}
        original=copy.deepcopy((rows, plan))
        self.facts(rows, plan=plan)
        self.assertEqual(original, (rows, plan))

    def test_listing_errors_are_visible_not_claimed_missing(self):
        result = self.facts([dict(id='a')], plan={'feed_error':'Pagination interrupted'})
        self.assertEqual(('Pagination interrupted',), result.warnings)
        self.assertIn('Listing warnings', result.status)

    def test_singular_and_plural_are_consistent(self):
        self.assertEqual('1 chapter entry', entry_text(1))
        self.assertEqual('2 chapter entries', entry_text(2))


class FileListingTests(unittest.TestCase):
    def test_parser_contract_invalidates_only_affected_query_qualifications(self):
        from calibre_plugins.manganana.discovery.search_resolution import inventory_cache_key, snapshot_inventory_contract_changed
        from calibre_plugins.manganana.providers.source_registry import SourceRegistry
        source=WeebCentralSource()
        registry=SourceRegistry((source,))
        row={'url':'https://weebcentral.com/series/01J76XY7HA6DH9YYGREDVPH8W5/Detective-Conan'}
        key=inventory_cache_key(source,row,'en')
        self.assertTrue(snapshot_inventory_contract_changed(registry,{'inventory_keys':[key[:-1]]}))
        self.assertFalse(snapshot_inventory_contract_changed(registry,{'inventory_keys':[key]}))
        self.assertFalse(snapshot_inventory_contract_changed(registry,{'inventory_keys':[('acquisition','mangadex','id','en','original')]}))

    def test_old_cached_empty_conan_cannot_mask_new_parser_and_warm_reuses_rows(self):
        from calibre_plugins.manganana.publication.inventory_comparison import SourceInventory
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
        from calibre_plugins.manganana.discovery.search_resolution import inventory_cache_key, _inventory_cache_put, cached_source_inventory
        text=(ROOT/'build/chapter-mode-search-thumbnail/live-details/responses/013.html').read_text(encoding='utf-8')
        calls=[]
        def fetch(url,**kwargs):
            calls.append(url)
            return text
        source=WeebCentralSource(fetch_text=fetch)
        row={'source_id':'weebcentral','id':'01J76XY7HA6DH9YYGREDVPH8W5','url':'https://weebcentral.com/series/01J76XY7HA6DH9YYGREDVPH8W5/Detective-Conan'}
        key=inventory_cache_key(source,row,'en')
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            old=SourceInventory(source_id=source.source_id,source_name=source.display_name,result=row,language='en',edition='original')
            _inventory_cache_put(cache,key[:-1],old)
            fresh=cached_source_inventory(cache,source,row,'en','chapter')
            warm=cached_source_inventory(cache,source,row,'en','chapter')
            self.assertEqual((1169,1169),(fresh.chapter_count,warm.chapter_count))
            self.assertEqual(1,len(calls))
            self.assertIsNotNone(cache.get_inventory(key[:-1]))
            cache.close()

    def test_captured_conan_all_file_ids_are_recovered(self):
        text=(ROOT/'build/chapter-mode-search-thumbnail/live-details/responses/013.html').read_text(encoding='utf-8')
        url='https://weebcentral.com/series/01J76XY7HA6DH9YYGREDVPH8W5/Detective-Conan'
        calls=[]
        def fetch(value, **kwargs):
            calls.append(value)
            return text
        rows=WeebCentralSource(fetch_text=fetch).get_chapters(url,'en')
        raw=re.findall(r'<a[^>]+href="/chapters/([0-9A-Z]{26})"[^>]*>(.*?)</a>',text,re.I|re.S)
        expected={record_id.upper() for record_id,body in raw if re.search(r'\bFile\s+\d+',body,re.I)}
        self.assertEqual(1169,len(rows))
        self.assertEqual(expected,{row['id'] for row in rows})
        self.assertEqual(1,len(calls))
        self.assertTrue(all(row['volume'] is None for row in rows))
        self.assertEqual('File 1',rows[0]['original_label'])
        self.assertEqual('File 1169',rows[-1]['original_label'])

    def test_file_label_does_not_change_prologue_namespace(self):
        labels=('File 1','Chapter 2','Episode 3','Prologue 1')
        text=''.join(f'<a href="/chapters/{i:026}">{value}</a>' for i,value in enumerate(labels))
        rows=WeebCentralSource(fetch_text=lambda *a,**k:text).get_chapters('https://weebcentral.com/series/01J76XY7HA6DH9YYGREDVPH8W5/x','en')
        self.assertEqual({'1','2','3','Prologue 1'},{row['chapter'] for row in rows})
        self.assertEqual('prologue',next(row for row in rows if row['chapter']=='Prologue 1')['numbering_group'])


if __name__ == '__main__':
    unittest.main()
