import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from calibre_plugins.manganana.diagnostics import diagnostics as diag

class DiagnosticBurstTests(unittest.TestCase):
    def setUp(self):
        diag._RECENT.clear()
    def write(self,directory,error='missing d'):
        return diag.write_diagnostic_report(directory,version='test',build_id='snapshot',mode='volume',
            provider='MangaDex',operation='Qt callback',exc=AttributeError(error))
    def test_80809_identical_errors_are_bounded_and_counted(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(diag.time,'monotonic',return_value=1):
            self.assertIsNotNone(self.write(directory))
            for _ in range(80808):self.assertIsNone(self.write(directory))
            report=(Path(directory)/'MangaNana-diagnostics.log').read_text()
            self.assertEqual(1,report.count('MangaNana diagnostic report'))
            self.assertLess(len(report),4096)
            self.assertEqual(80809,next(iter(diag._RECENT.values()))['count'])
            self.assertIn('Occurrences: 10000',report)
            diag.flush_diagnostic_summaries(directory)
            self.assertIn('Occurrences: 80809',(Path(directory)/'MangaNana-diagnostics.log').read_text())
            self.assertIsNotNone(self.write(directory,'different error'))
    def test_rotation_and_fingerprints_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(diag,'_MAX_LOG_BYTES',1024):
            for i in range(160):self.write(directory,str(i))
            self.assertEqual(128,len(diag._RECENT))
            self.assertLessEqual((Path(directory)/'MangaNana-diagnostics.log').stat().st_size,1024)
            self.assertLessEqual((Path(directory)/'MangaNana-diagnostics.previous.log').stat().st_size,1024)

if __name__=='__main__':unittest.main()
