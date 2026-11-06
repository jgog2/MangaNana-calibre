"""Mixed ranges stay evidence until their chapter namespace is established."""
import unittest
from tests.test_wikipedia_membership import graphic, parsed


class MixedUncollectedContract(unittest.TestCase):
    def tail(self, expression):
        return parsed(graphic('*Mission: 1–3','1')+
            '\n== Chapters not yet in tankōbon format ==\n*Mission: '+expression)[2]

    def test_integer_uncollected_range_remains_exact(self):
        result=self.tail('4–6')
        self.assertEqual(['4','5','6'],[r.number for r in result['chapters'] if r.kind=='uncollected'])

    def test_terminal_decimal_is_not_an_enumeration_contract(self):
        for expression in ('4–6.1','4–6.5'):
            result=self.tail(expression)
            row=next(r for r in result['chapters'] if r.number==expression)
            self.assertEqual(('uncollected_range',''),(row.kind,row.volume))
            self.assertFalse(any(r.kind=='uncollected' for r in result['chapters']))
            self.assertTrue(row.source_record_id and row.source_revision_id)

    def test_mixed_range_in_collected_context_does_not_gain_numeric_identity(self):
        for expression in ('4–6.1','4–6.5'):
            _,_,result=parsed(graphic('*Mission: '+expression))
            self.assertEqual([(expression,'range','6')],[(r.number,r.kind,r.volume) for r in result['chapters']])

    def test_reversed_malformed_decimal_start_and_arbitrary_decimal_ranges_fail_closed(self):
        for expression in ('6.1–4','6.5–4','4--6.1','4–','4.1–6','4.1–6.1','4.5–6.5',
                           'A–F','4–1000000.1','4, 5–6.1'):
            result=self.tail(expression)
            self.assertFalse(any(r.kind=='uncollected' for r in result['chapters']))
            row=next(r for r in result['chapters'] if r.number==expression)
            self.assertEqual(('uncollected_range',''),(row.kind,row.volume))

    def test_individual_decimal_is_exact_and_provenance_survives_cache(self):
        adapter,match,_=parsed(graphic('*Mission: 4.1, 4.5'))
        saved={};first=adapter.resolve_publication(match,segment_cache_put=saved.__setitem__)
        second=adapter.resolve_publication(match,segment_cache_get=saved.get)
        self.assertEqual(['4.1','4.5'],[r.number for r in second['chapters']])
        self.assertEqual(first['chapters'],second['chapters'])


if __name__=='__main__':unittest.main()
