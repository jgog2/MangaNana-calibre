"""Explicit retry conserves exact output ownership and never repeats successes."""
import copy
import tempfile
import unittest
from pathlib import Path
from calibre_plugins.manganana.books.imports.output_import import prepared_retry


class RecoveryTests(unittest.TestCase):
    def test_mixed_results_retry_only_unique_prepared_unresolved_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = [dict(output_identity=str(i), title='Same title', output_acquisition={'record': str(i)}) for i in range(6)]
            files = []
            for row in rows[:5]:
                path = Path(folder) / (row['output_identity'] + '.cbz'); path.write_bytes(b'prepared')
                files.append(dict(row, path=str(path), series_index=67.5))
            ledger = dict(outputs=[dict(row, status=status, generated=i < 5) for i, (row, status) in
                enumerate(zip(rows, ('imported', 'updated', 'skipped', 'conflicted', 'failed', 'failed')))], unexpected=[])
            original = copy.deepcopy((rows, files, ledger))
            requests, result = prepared_retry(rows, dict(files=files, failures=[{'error': 'generation failed'}]), ledger)
            self.assertEqual(['3', '4'], [r['output_identity'] for r in requests])
            self.assertEqual([67.5, 67.5], [r['series_index'] for r in result['files']])
            self.assertTrue(result['preserve_workdir']); self.assertFalse(result['failures'])
            self.assertEqual(['5'],[row['output_identity']for row in result['recovery_remaining']])
            requests[0]['output_acquisition']['record'] = 'changed'
            self.assertEqual(original, (rows, files, ledger))

    def test_ambiguous_missing_and_successful_files_are_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.cbz'; path.write_bytes(b'a')
            row = dict(output_identity='a', path=str(path))
            ledger = dict(outputs=[dict(output_identity='a', generated=True, status='failed')])
            self.assertIsNone(prepared_retry([row], dict(files=[row, row]), ledger))
            path.unlink()
            self.assertIsNone(prepared_retry([row], dict(files=[row]), ledger))

    def test_retry_only_failure_can_release_directory_after_normal_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.cbz'; path.write_bytes(b'a')
            row = dict(output_identity='a', path=str(path))
            ledger = dict(outputs=[dict(output_identity='a', generated=True, status='failed')])
            self.assertFalse(prepared_retry([row], dict(files=[row]), ledger)[1]['preserve_workdir'])

    def test_completion_results_preserve_reason_and_file_path(self):
        from qt.core import QApplication
        from calibre_plugins.manganana.app.notifications.completion_dialog import CompletionDialog
        app = QApplication.instance() or QApplication([])
        dialog = CompletionDialog()
        dialog.setLedger(dict(outputs=[dict(title='A', status='conflicted', reason='Identity collision', generated_file='retained.cbz')]))
        self.assertEqual('Conflicted', dialog.table.item(0, 1).text())
        self.assertIn('retained.cbz', dialog.table.item(0, 2).toolTip())
        for label in ('OK', 'Library', 'Added', 'Files', 'Retry'):
            dialog.addButton(label, None)
        self.assertEqual(2, dialog.actions.rowCount())
        dialog.deleteLater(); app.processEvents()

    def test_setting_aside_recovery_is_guarded_and_never_deletes_prepared_files(self):
        from types import SimpleNamespace
        from qt.core import QApplication, QDialog, QVBoxLayout
        from calibre_plugins.manganana.presentation.non_modal_window import NonModalSession
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'prepared.cbz';path.write_bytes(b'retained')
            d=QDialog();d._closing=False;d._download_in_progress=False
            d.footer=SimpleNamespace(stack=QVBoxLayout(d))
            d.destination=SimpleNamespace(available=lambda:True,identity=SimpleNamespace(path=folder))
            logs=[];d.add_log=logs.append
            session=NonModalSession(d);pending=dict(result=dict(workdir=folder));session.pending=pending
            d._download_in_progress=True;session.release_pending();self.assertIs(pending,session.pending)
            d._download_in_progress=False;d._closing=True;session.release_pending();self.assertIs(pending,session.pending)
            d._closing=False;session.release_pending()
            self.assertIsNone(session.pending);self.assertEqual(b'retained',path.read_bytes());self.assertTrue(logs)
            session.detach();d.deleteLater();app.processEvents()
