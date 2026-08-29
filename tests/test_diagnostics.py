from pathlib import Path
import tempfile
import unittest

from diagnostics import redact_sensitive_text, write_diagnostic_report


class DiagnosticTests(unittest.TestCase):
    def test_report_records_context_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            try:
                raise RuntimeError('token=private-value password: nope Bearer abc123')
            except RuntimeError as exc:
                path=write_diagnostic_report(
                    directory, version='0.10.0-dev — The Magician', build_id='abc1234',
                    mode='chapter', provider='MangaPill', operation='chapter inventory load',
                    exc_type=type(exc), exc=exc, tb=exc.__traceback__,
                )
            report=Path(path).read_text(encoding='utf-8')
            self.assertIn('Version: 0.10.0-dev — The Magician', report)
            self.assertIn('Build: abc1234', report)
            self.assertIn('Workflow mode: chapter', report)
            self.assertIn('Provider: MangaPill', report)
            self.assertIn('Traceback:', report)
            self.assertNotIn('private-value', report)
            self.assertNotIn('nope', report)

    def test_redaction_handles_common_secret_forms(self):
        self.assertEqual('cookie=[redacted]', redact_sensitive_text('cookie=abc'))
        self.assertEqual('Bearer [redacted]', redact_sensitive_text('Bearer abc.def'))


if __name__ == '__main__':
    unittest.main()
