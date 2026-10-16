"""Run: python -m unittest discover -s tests -v"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import storage
import publish
from transform import basic_extract, format_post, preferred_url


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict('os.environ', {'TELEGRAM_TARGET_CHANNEL':'@general_channel', 'TELEGRAM_EDUCATION_CHANNEL':'@education_channel'})
        self.environment.start()
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = storage.DB_PATH
        self.old_dir = storage.DATA_DIR
        storage.DB_PATH = Path(self.temp.name) / "opportunities.db"
        storage.DATA_DIR = Path(self.temp.name)
        storage.init_db()

    def tearDown(self):
        storage.DB_PATH = self.old_path
        storage.DATA_DIR = self.old_dir
        self.temp.cleanup()
        self.environment.stop()

    def opportunity(self, name="Test opportunity", url="https://example.org/jobs/123", deadline=""):
        return dict(source_key="manual:" + name + url, title=name, organization="Example Org",
                    category="Job", raw_text=name, apply_url=url, source_url=url, source_name="Test",
                    description="Brief sample", deadline=deadline)

    def test_add_and_deduplicate(self):
        self.assertTrue(storage.add_opportunity(self.opportunity()))
        self.assertFalse(storage.add_opportunity(self.opportunity()))
        self.assertTrue(storage.add_opportunity(self.opportunity("Another title")))  # Different roles can share a portal.
        self.assertEqual(len(storage.get_opportunities()), 2)

    def test_tracking_and_once_per_slot(self):
        storage.add_opportunity(self.opportunity())
        oid = storage.get_opportunities()[0]["id"]
        storage.update_opportunity(oid, {}, status="approved")
        first = storage.claim_next("telegram", "2026-10-14-08")
        self.assertEqual(first["id"], oid)
        self.assertIsNone(storage.claim_next("telegram", "2026-10-14-08"))
        self.assertIsNone(storage.claim_next("telegram", "2026-10-14-10"))
        # Same opportunity is still eligible for other platform.
        second = storage.claim_next("linkedin", "2026-10-14-08")
        self.assertEqual(second["id"], oid)
        storage.set_publication(oid, "telegram", "posted", "321")
        telegram = [p for p in storage.get_publications() if p["platform"] == "telegram"][0]
        self.assertEqual(telegram["status"], "posted")

    def test_rejected_not_posted(self):
        storage.add_opportunity(self.opportunity())
        self.assertIsNone(storage.claim_next("telegram", "slot-1"))
        storage.update_opportunity(storage.get_opportunities()[0]["id"], {}, status="rejected")
        self.assertIsNone(storage.claim_next("telegram", "slot-2"))

    def test_expired_deadline_skipped(self):
        yesterday = (datetime.now(timezone(timedelta(hours=3))) - timedelta(days=1)).date().isoformat()
        storage.add_opportunity(self.opportunity(deadline=yesterday))
        oid = storage.get_opportunities()[0]["id"]
        storage.update_opportunity(oid, {}, status="approved")
        self.assertIsNone(storage.claim_next("telegram", "slot-expired"))

    def test_url_normalization(self):
        self.assertEqual(storage.canonical_url("https://EXAMPLE.com/jobs/123/?utm_source=abc"),
                         "https://example.com/jobs/123")
        self.assertEqual(preferred_url("https://t.me/source/1 and https://www.example.org/apply"),
                         "https://www.example.org/apply")

    def test_basic_extraction_and_format(self):
        opp = basic_extract("Scholarship for students\nApply at https://example.org/apply", "Example")
        self.assertEqual(opp["category"], "Scholarship")
        self.assertEqual(opp["deadline"], "")
        formatted = format_post(opp, "telegram")
        self.assertIn("example.org/apply", formatted)
        self.assertIn("Deadline: Not specified", formatted)

    def test_slot_timezone(self):
        with patch("publish.config", return_value={"publish_hours": [8, 10, 12]}):
            self.assertEqual(publish.scheduled_slot(datetime(2026, 10, 14, 8, 10,
                            tzinfo=timezone(timedelta(hours=3)))), "2026-10-14-08")
            self.assertIsNone(publish.scheduled_slot(datetime(2026, 10, 14, 9, 10,
                            tzinfo=timezone(timedelta(hours=3)))))

    def test_publisher_sends_and_records(self):
        storage.add_opportunity(self.opportunity())
        oid = storage.get_opportunities()[0]["id"]
        storage.update_opportunity(oid, {}, status="approved")
        with patch("publish.send_telegram", return_value="message-123") as mock:
            result = publish.publish_one("telegram", "manual-slot")
            self.assertIn("posted", result)
            self.assertEqual(mock.call_count, 1)
        self.assertEqual(storage.get_publications()[0]["remote_id"], "message-123")
        self.assertIn("no new", publish.publish_one("telegram", "manual-slot"))

    def test_manual_linkedin_mark(self):
        storage.add_opportunity(self.opportunity())
        oid = storage.get_opportunities()[0]["id"]
        self.assertTrue(storage.mark_manual_linkedin(oid))
        self.assertFalse(storage.mark_manual_linkedin(oid))


if __name__ == "__main__":
    unittest.main()
