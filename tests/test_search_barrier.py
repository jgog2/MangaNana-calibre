import unittest

from inventory_comparison import SourceInventory, compare_inventories
from search_barrier import ProviderDisplayBarrier
from search_ranking import rank_canonical_results


class SearchDisplayBarrierTests(unittest.TestCase):
    def _run(self, response_order):
        inventories={
            'mangadex':SourceInventory('mangadex','MangaDex',{},'en','original',chapter_count=0,usable=False),
            'mangapill':SourceInventory('mangapill','MangaPill',{},'en','original',standalone_chapters=100,chapter_count=100,usable=True,complete=True),
            'weebcentral':SourceInventory('weebcentral','WeebCentral',{},'en','original',standalone_chapters=98,chapter_count=98,usable=True,complete=True),
        }
        search_rows={
            'mangadex':(
                {'source_id':'mangadex','id':'opm-dex','title':'One Punch Man','alternate_titles':[]},
                {'source_id':'mangadex','id':'noise-dex','title':'A Crossover With One Punch in Another World','alternate_titles':[]},
            ),
            'mangapill':(
                {'source_id':'mangapill','id':'opm-pill','title':'One-Punch Man','alternate_titles':[]},
            ),
            'weebcentral':(
                {'source_id':'weebcentral','id':'opm-weeb','title':'One Punch Man','alternate_titles':[]},
            ),
        }
        barrier=ProviderDisplayBarrier(('mangadex','mangapill','weebcentral'))
        for source_id in response_order:
            barrier.settle(source_id,'success',{
                'source_id':source_id,
                'inventory':inventories[source_id],
                'results':search_rows[source_id],
            })
        ordered=barrier.ordered_successes()
        decision=compare_inventories(tuple(page['inventory'] for page in ordered),workflow='chapter')
        resolved=decision.selected or sorted(
            decision.equivalent_inventories,key=lambda row:(-row.chapter_count,row.source_id)
        )[0]
        ranked=rank_canonical_results(
            'One Punch',tuple(row for page in ordered for row in page['results'])
        )
        return (
            tuple(page['source_id'] for page in ordered),
            tuple(row.group.display_title for row in ranked),
            decision,
            resolved.source_id,
        )

    def test_fast_mangadex_and_slow_mangadex_permutations_are_identical(self):
        fast_order,fast_ranking,fast_decision,fast_provider=self._run(('mangadex','mangapill','weebcentral'))
        slow_order,slow_ranking,slow_decision,slow_provider=self._run(('mangapill','weebcentral','mangadex'))
        self.assertEqual(fast_order,slow_order)
        self.assertEqual(fast_ranking,slow_ranking)
        self.assertEqual('One Punch Man',fast_ranking[0])
        self.assertEqual(fast_provider,slow_provider)
        self.assertEqual(fast_decision.selected,slow_decision.selected)
        self.assertEqual(
            [row.source_id for row in fast_decision.equivalent_inventories],
            [row.source_id for row in slow_decision.equivalent_inventories],
        )

    def test_failure_and_timeout_are_terminal_and_do_not_block(self):
        barrier=ProviderDisplayBarrier(('mangadex','mangapill','weebcentral'))
        barrier.settle('mangadex','failure')
        barrier.settle('mangapill','success',{'rows':[1]})
        self.assertFalse(barrier.complete)
        barrier.settle('weebcentral','timeout')
        self.assertTrue(barrier.complete)
        self.assertEqual(({'rows':[1]},),barrier.ordered_successes())

    def test_no_success_payload_is_released_before_barrier(self):
        barrier=ProviderDisplayBarrier(('mangadex','mangapill'))
        barrier.settle('mangadex','success',{'rows':['early']})
        self.assertEqual((),barrier.ordered_successes())
        barrier.settle('mangapill','cancelled')
        self.assertEqual(({'rows':['early']},),barrier.ordered_successes())


if __name__ == '__main__':
    unittest.main()
