"""Exact special taxonomy must survive acquisition projection and ranking."""
from dataclasses import replace
import unittest

from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.publication.inventory_comparison import SourceInventory, compare_inventories
from calibre_plugins.manganana.discovery.search_resolution import _choose_primary
from calibre_plugins.manganana.publication.publication_specials import inventory_coverage, explicit_special_title
from calibre_plugins.manganana.publication.chapter_workflow import chapter_sort_key


def reference(records):
    return dict(status='valid',cache_contract='mangadex-structure-v1',canonical_work_id='fixture:work',
        edition_profile='standard',manga_id='11111111-1111-1111-1111-111111111111',
        mappings={r['key']:r['volume'] for r in records if r.get('volume')},
        special_metadata_contract='mangadex-specials-v1',special_records=records)


def special(key='2.5',volume='1',kind='bonus',**kw):
    return dict(key=key,kind=kind,volume=volume,source='mangadex_structure',confidence='explicit',
        source_record_id='reference:'+key,source_page='https://mangadex.org/chapter/reference-'+key,**kw)


def project(rows,records):
    b=PublicationManifestBuilder({'canonical_identity':'fixture:work'},'original')
    b.apply_provider_inventory(rows,'mangapill').apply_mangadex_structure(reference(records))
    return build_publication_projection(rows,b.build(),'mangapill','mangapill')


class PublicationSpecials(unittest.TestCase):
    def test_explicit_special_type_and_provenance_survive_projection(self):
        row=dict(chapter='2.5',id='reader:2.5')
        out=project([row],[special()]).rows[0]
        self.assertEqual('bonus',out.get('type'))
        self.assertEqual('mangadex_structure',out.get('_type_source'))
        self.assertEqual('1',out['_effective_volume']);self.assertEqual('reader:2.5',out['id'])
        self.assertNotIn('type',row)

    def test_special_without_membership_does_not_inherit_parent_volume(self):
        rows=[dict(chapter='10',id='ten',volume='2'),dict(chapter='10.5',id='bonus')]
        out=project(rows,[special('10.5',volume='')]).rows[1]
        self.assertEqual('bonus',out.get('type'));self.assertNotIn('_effective_volume',out)
        self.assertEqual('2',project(rows,[special('10.5',volume='2')]).rows[1]['_effective_volume'])

    def test_exact_source_record_link_can_select_canonical_label_without_numeric_fuzz(self):
        row=dict(chapter='2.1',id='reader:y')
        self.assertNotEqual('bonus',project([row],[special()]).rows[0].get('type'))
        proof=special(aliases=[dict(source='mangapill',record_id='reader:y',identifier='2.1')])
        out=project([row],[proof]).rows[0]
        self.assertEqual(('2.5','2.1','reader:y','bonus'),
                         (out['chapter'],out['_acquisition_chapter'],out['id'],out['type']))
        bad=dict(row,id='other');self.assertNotEqual('bonus',project([bad],[proof]).rows[0].get('type'))

    def test_wrong_edition_and_conflicting_type_fail_closed(self):
        ref=reference([special()]);ref['edition_profile']='omnibus'
        b=PublicationManifestBuilder({'canonical_identity':'fixture:work'},'original').apply_mangadex_structure(ref)
        self.assertNotEqual('bonus',build_publication_projection([dict(chapter='2.5')],b.build()).rows[0].get('type'))
        out=project([dict(chapter='2.5')],[special(),special(kind='chapter')]).rows[0]
        self.assertNotEqual('bonus',out.get('type'))

    def test_raw_fractional_rows_do_not_increase_main_coverage_or_source_rank(self):
        rows=tuple(dict(chapter=str(n),id=str(n)) for n in range(1,247))
        clean=SourceInventory('atsu','Atsu',{},'en','original',chapter_count=246,usable=True,complete=True,chapter_records=rows)
        noisy=replace(clean,source_id='mangapill',source_name='MangaPill',chapter_count=250,
            chapter_records=rows+tuple(dict(chapter=f'{n}.5',id=f'x{n}') for n in (5,14,23,32)))
        self.assertEqual('atsu',_choose_primary((noisy,clean),'chapter').source_id)
        self.assertTrue(compare_inventories((noisy,clean),workflow='chapter').ambiguous)

    def test_specials_do_not_inflate_main_and_can_enrich_coverage(self):
        rows=tuple(dict(chapter=str(n),id=str(n)) for n in range(1,247))
        clean=SourceInventory('atsu','Atsu',{},'en','original',chapter_count=246,usable=True,complete=True,chapter_records=rows)
        records=[special(str(n)+'.5') for n in (5,14,23,32)]
        rich=replace(clean,source_id='mangapill',chapter_count=250,
            chapter_records=rows+tuple(dict(chapter=r['key'],id='bonus:'+r['key']) for r in records))
        self.assertEqual(dict(main=246,specials=4,unresolved=0,raw=250),inventory_coverage(rich,records))
        self.assertEqual('mangapill',_choose_primary((clean,rich),'chapter',records).source_id)
        self.assertTrue(compare_inventories((clean,rich),workflow='chapter',special_records=records).ambiguous)

    def test_sort_preserves_fractional_order_and_zero(self):
        rows=[dict(chapter=k,id=k) for k in ('27','26.5','0','26.1','26')]
        self.assertEqual(['0','26','26.1','26.5','27'],[r['chapter'] for r in sorted(rows,key=chapter_sort_key)])

    def test_category_heading_is_explicit_not_incidental_story_title(self):
        for text in ('Extra strength','Special delivery','A bonus for everyone','Chapter 10',''):
            self.assertIsNone(explicit_special_title(text))
        for text,kind in (('Bonus','bonus'),('Omake & Extras','special'),('One-Shot, Omake & Extras','special'),('Extra','extra')):
            self.assertEqual(kind,explicit_special_title(text))

    def test_scoped_taxonomy_rejects_other_work_stale_and_conflicting_volume(self):
        from calibre_plugins.manganana.publication.publication_specials import canonical_special_records
        ref=reference([special()])
        for field,value in (('canonical_work_id','other'),('cache_state','last_known_good'),('status','transient_failure')):
            bad=dict(ref,**{field:value})
            self.assertEqual([],canonical_special_records({'mangadex_structure':bad},'fixture:work','original','en',{}))
        ref=reference([special(),special(volume='2')])
        self.assertEqual([],canonical_special_records({'mangadex_structure':ref},'fixture:work','original','en',{}))

    def test_named_provider_special_is_retained_with_actual_download_id(self):
        row=dict(chapter='Bonus',id='actual-reader',type='bonus',title='Bonus')
        out=project([row],[]).rows[0]
        self.assertEqual(('Bonus','actual-reader','bonus'),(out['chapter'],out['id'],out['type']))


if __name__=='__main__':unittest.main()
