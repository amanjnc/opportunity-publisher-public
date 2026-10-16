import unittest
from unittest.mock import patch
from datetime import datetime
import storage, roundup
import test_cloud

class RenameTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    add=test_cloud.CloudTests.add
    def populate(self):
        self.add('A useful scholarship opportunity','https://example.org/apply','2026-10-17')
        item=storage.get_opportunities()[0];storage.update_opportunity(item['id'],{},status='approved')
        storage.claim_next('telegram','slot');storage.set_publication(item['id'],'telegram','posted','123')
        with storage.db() as c:
            c.execute("UPDATE publications SET destination='@old_channel'")
            c.execute("INSERT INTO weekly_roundups(week_key,status,text,remote_id,created_at) VALUES('@old_channel:2026-10-12','posted','Historical text','42','2026-10-12')")
    def test_rename_preserves_guard_and_new_links(self):
        self.populate()
        with patch('roundup.env',return_value='@new_channel'):
            self.assertEqual(roundup.sync_roundup_destination(),'@old_channel')
            self.assertEqual(roundup.sync_roundup_destination(),'')
            _,text,count=roundup.build_roundup(datetime(2026,10,16,tzinfo=roundup.TZ))
        self.assertEqual(count,1);self.assertIn('https://t.me/new_channel/123',text)
        with storage.db() as c:
            self.assertEqual(c.execute("SELECT status FROM weekly_roundups WHERE week_key='@new_channel:2026-10-12'").fetchone()[0],'posted')
    def test_conflicting_channels_not_merged(self):
        self.populate()
        with storage.db() as c:c.execute("UPDATE publications SET destination='@other_channel'")
        # Add a second saved publication destination.
        self.add('A distinct training opportunity','https://example.org/other')
        item=next(o for o in storage.get_opportunities() if o['title']=='A distinct training opportunity');storage.update_opportunity(item['id'],{},status='approved');storage.claim_next('telegram','slot2')
        with storage.db() as c:c.execute("UPDATE publications SET destination='@old_channel' WHERE slot_key='slot2'")
        with patch('roundup.env',return_value='@new_channel'):
            with self.assertRaises(ValueError):roundup.sync_roundup_destination()
        with storage.db() as c:self.assertEqual(c.execute("SELECT count(*) FROM publications WHERE destination='@new_channel'").fetchone()[0],0)
