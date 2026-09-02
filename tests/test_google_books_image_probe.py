import importlib.util
from pathlib import Path
import unittest


SPEC=importlib.util.spec_from_file_location('google_image_probe',Path(__file__).resolve().parents[1]/'tools'/'probe_google_books_image_retrieval.py')
PROBE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(PROBE)


class GoogleBooksImageProbeTests(unittest.TestCase):
    def test_redaction_never_exposes_key(self):
        value=PROBE.redact_url('https://x.test/a?key=secret&keep=value')
        self.assertNotIn('secret',value); self.assertIn('key=REDACTED',value); self.assertIn('keep=value',value)

    def test_quality_uses_measured_width(self):
        self.assertEqual('HIGH',PROBE.quality(575,900))
        self.assertEqual('USABLE',PROBE.quality(300,450))
        self.assertEqual('THUMBNAIL_ONLY',PROBE.quality(100,150))
        self.assertEqual('TINY',PROBE.quality(99,148))
        self.assertEqual('PLACEHOLDER',PROBE.quality(900,1200,True))

    def test_same_cover_requires_compatible_aspect_and_perceptual_hash(self):
        official={'decodable':True,'width':128,'aspect_ratio':.67,'perceptual_hash':'0'*256}
        close={'decodable':True,'width':600,'aspect_ratio':.68,'perceptual_hash':'0'*250+'1'*6}
        wrong={'decodable':True,'width':600,'aspect_ratio':1.0,'perceptual_hash':'1'*256}
        self.assertTrue(PROBE.same_cover(official,close))
        self.assertFalse(PROBE.same_cover(official,wrong))

    def test_variants_are_bounded_to_recognized_zoom_urls(self):
        self.assertEqual((),PROBE._variants('https://x.test/image.jpg'))
        values=PROBE._variants('https://x.test/image.jpg?zoom=1&edge=curl')
        self.assertEqual(2,len(values)); self.assertTrue(all('zoom=' in value for value in values))

    def test_best_attempt_is_deterministic_and_rejects_wrong_cover(self):
        attempts=[
            {'method':'wrong','quality':'HIGH','same_cover':False,'placeholder':False,'bytes':99},
            {'method':'b','quality':'USABLE','same_cover':True,'placeholder':False,'bytes':10,'requested_url':'b'},
            {'method':'a','quality':'USABLE','same_cover':True,'placeholder':False,'bytes':10,'requested_url':'a'},
        ]
        self.assertEqual('a',PROBE.best_attempt(attempts)['method'])


if __name__=='__main__': unittest.main()
