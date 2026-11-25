"""Run with:  python -m unittest discover tests"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import fetch_jobs  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

CONFIG = {"cities": ["Seattle", "Kirkland"], "allow_remote": True,
          "title_keywords": [], "greenhouse_boards": ["acme"], "lever_companies": ["beta"]}

GREENHOUSE = {"jobs": [
    {"id": 1, "title": "Operations Coordinator", "location": {"name": "Seattle, WA"},
     "content": "&lt;p&gt;Keep things running &amp;amp; tidy.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Sheets&lt;/li&gt;&lt;/ul&gt;",
     "absolute_url": "https://example.com/1", "updated_at": "2026-11-20T00:00:00Z"},
    {"id": 2, "title": "Ops Associate", "location": {"name": "London, UK"},
     "content": "", "absolute_url": "", "updated_at": ""},
]}

LEVER = [
    {"id": "abc", "text": "AI Evaluator", "categories": {"location": "Anywhere"},
     "workplaceType": "remote", "descriptionPlain": "Grade model answers.",
     "lists": [{"text": "You have", "content": "<li>Good judgment</li>"}],
     "hostedUrl": "https://example.com/abc", "salaryRange": {"min": 30, "max": 40, "currency": "USD"}},
]


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        fetch_jobs.INBOX = self.tmp / "inbox"
        fetch_jobs.SEEN_FILE = self.tmp / "seen.json"

    def test_indeed_import_parses_and_dedupes(self):
        f = str(FIXTURES / "indeed_job.md")
        seen = {}
        self.assertEqual(fetch_jobs.import_indeed([f], seen), 1)
        text = (fetch_jobs.INBOX / "indeed-JOBSEARCH_100281.txt").read_text()
        lines = text.splitlines()
        self.assertEqual(lines[0], "Business Operations Coordinator")
        self.assertIn("Company: Network Architects", text)
        self.assertIn("Pay: $65,000 - $85,000 a year", text)
        self.assertIn("2+ years of experience", text)
        self.assertNotIn("**", text.split("\n\n", 1)[1])
        # second import of the same job does nothing
        self.assertEqual(fetch_jobs.import_indeed([f], seen), 0)

    def test_same_job_new_id_is_skipped(self):
        seen = {}
        args = dict(title="Ops Coordinator", company="Acme", location="Seattle, WA",
                    description="x")
        self.assertIsNotNone(fetch_jobs.save_posting(seen, "indeed", "1", **args))
        self.assertIsNone(fetch_jobs.save_posting(seen, "indeed", "2", **args))

    def test_boards_filter_location_and_convert_html(self):
        def fake_get_json(url):
            return GREENHOUSE if "greenhouse" in url else LEVER
        fetch_jobs.get_json = fake_get_json
        seen = {}
        self.assertEqual(fetch_jobs.pull_boards(CONFIG, seen), 2)  # London dropped
        gh = (fetch_jobs.INBOX / "greenhouse-acme-1.txt").read_text()
        self.assertIn("Keep things running & tidy.", gh)
        self.assertIn("- Sheets", gh)
        lv = (fetch_jobs.INBOX / "lever-beta-abc.txt").read_text()
        self.assertIn("Location: Anywhere (Remote)", lv)
        self.assertIn("- Good judgment", lv)
        self.assertIn("Pay: 30 - 40 USD", lv)
        self.assertEqual(fetch_jobs.pull_boards(CONFIG, seen), 0)

    def test_location_rule(self):
        self.assertTrue(fetch_jobs.is_wanted_location("Kirkland, WA", CONFIG))
        self.assertTrue(fetch_jobs.is_wanted_location("Remote - US", CONFIG))
        self.assertTrue(fetch_jobs.is_wanted_location("", CONFIG))
        self.assertFalse(fetch_jobs.is_wanted_location("Austin, TX", CONFIG))


if __name__ == "__main__":
    unittest.main()
