"""Tests for MangaNana's centralized semantic and codename identity."""

from pathlib import Path
import unittest

from tools.build_plugin import build_info_source
from version_info import (
    CALIBRE_VERSION,
    CODENAME,
    DISPLAY_VERSION,
    FUTURE_1_0_CODENAME,
    SEMANTIC_VERSION,
    SHORT_VERSION_LABEL,
    USER_AGENT,
)


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class VersionInfoTests(unittest.TestCase):
    def test_current_semantic_version_and_codename(self):
        self.assertEqual(SEMANTIC_VERSION, "0.11.0-dev")
        self.assertEqual(CODENAME, "The High Priestess")
        self.assertEqual(DISPLAY_VERSION, "MangaNana 0.11.0-dev — The High Priestess")
        self.assertEqual(SHORT_VERSION_LABEL, "v0.11.0-dev — The High Priestess")

    def test_main_header_uses_unclipped_central_short_label(self):
        main_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertIn("ver = QLabel(SHORT_VERSION_LABEL)", main_source)
        self.assertNotIn("ver.setFixedWidth(105)", main_source)

    def test_calibre_tuple_remains_numeric(self):
        self.assertEqual(CALIBRE_VERSION, (0, 11, 0))
        self.assertTrue(all(isinstance(component, int) for component in CALIBRE_VERSION))

    def test_user_agent_uses_authoritative_semantic_version(self):
        self.assertEqual(USER_AGENT, "MangaNana-Calibre/0.11.0-dev")

    def test_future_one_point_zero_codename_is_reserved(self):
        self.assertEqual(FUTURE_1_0_CODENAME, "The World")

    def test_generated_build_identity_has_commit_but_no_timestamp(self):
        generated = build_info_source(REPOSITORY_ROOT)
        self.assertIn("GIT_COMMIT", generated)
        self.assertNotRegex(generated, r"\d{8}-\d{6}Z")
        self.assertNotIn("DISPLAY_VERSION", generated)
        namespace = {}
        exec(generated, namespace)
        self.assertRegex(namespace["GIT_COMMIT"], r"^(?:[0-9a-f]{7}|unknown)$")
        self.assertEqual(namespace["BUILD_ID"], namespace["GIT_COMMIT"])


if __name__ == "__main__":
    unittest.main()
