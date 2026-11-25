"""Run with:  python -m unittest discover tests"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily  # noqa: E402

POSTING = """Operations Coordinator
Company: Example Co
Location: Seattle, WA (Hybrid)
Pay: $24 an hour
URL: https://example.com/1
Source: indeed

0 to 2 years. Google Sheets and SOPs.
"""


class DailyTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(daily, name, tmp / sub) for name, sub in
                        [("INBOX", "inbox"), ("REPORTS", "reports"),
                         ("SEEN_FILE", "state/seen.txt")]]
        self.patches.append(mock.patch.object(daily, "FOLDER", tmp))
        for p in self.patches:
            p.start()
        (tmp / "inbox").mkdir()
        (tmp / "inbox" / "indeed-1.txt").write_text(POSTING)
        (tmp / "inbox" / "lever-2.txt").write_text("Staff Engineer\n\nAs a Staff Engineer, you will...")
        self.tmp = tmp

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_read_header(self):
        info = daily.read_header(POSTING)
        self.assertEqual(info["title"], "Operations Coordinator")
        self.assertEqual(info["company"], "Example Co")
        self.assertEqual(info["url"], "https://example.com/1")

    def test_only_apply_rows_kept_and_seen_once(self):
        answer = ({"decision": "Apply", "fit_score": 80, "reasons": ["r"],
                   "red_flags": [], "resume_bullets": ["b"]}, None)
        fake_triage = mock.MagicMock(ask_claude=mock.MagicMock(return_value=answer))
        with mock.patch.dict(sys.modules, {"triage": fake_triage}):
            daily.main([])
            report = next((self.tmp / "reports").glob("*.csv")).read_text()
            self.assertIn("indeed-1", report)
            self.assertNotIn("lever-2", report)  # layer one PASS, not sent
            # Second run: nothing new, Claude not called again
            fake_triage.ask_claude.reset_mock()
            daily.main([])
            fake_triage.ask_claude.assert_not_called()

    def test_failed_posting_is_retried(self):
        fake_triage = mock.MagicMock(ask_claude=mock.MagicMock(side_effect=ValueError("bad json")))
        with mock.patch.dict(sys.modules, {"triage": fake_triage}):
            daily.main([])
        self.assertNotIn("indeed-1", daily.load_seen())
        self.assertIn("lever-2", daily.load_seen())
        html = next((self.tmp / "reports").glob("*.html")).read_text()
        self.assertIn("Could not screen", html)


if __name__ == "__main__":
    unittest.main()
