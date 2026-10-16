import unittest
from unittest.mock import patch
from datetime import datetime
import test_cloud
import storage, publish, roundup
from routing import telegram_destination, telegram_routes

class RoutingTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    def add_item(self,category,title):
        storage.add_opportunity(dict(source_key=title,title=title,category=category,description='Factual details',apply_url='https://example.org/'+title.replace(' ','-'),deadline='2026-10-17'))
        item=next(o for o in storage.get_opportunities() if o['title']==title)
        storage.update_opportunity(item['id'],{},status='approved')
        return item
    def test_categories_route_correctly(self):
        for category in ('Scholarship','Fellowship',' scholarship '):self.assertEqual(telegram_destination({'category':category}),'@education_channel')
        for category in ('Job','Internship','Training','Volunteering','Other'):self.assertEqual(telegram_destination({'category':category}),'@general_channel')
    def test_missing_education_holds_without_claim(self):
        item=self.add_item('Scholarship','A scholarship for students')
        with patch.dict('os.environ',{'TELEGRAM_EDUCATION_CHANNEL':''}):
            self.assertIsNone(storage.claim_next('telegram','slot'))
        self.assertEqual(storage.get_publications(),[])
    def test_missing_education_does_not_block_general(self):
        self.add_item('Scholarship','A scholarship for students')
        job=self.add_item('Job','A distinct engineering role')
        with patch.dict('os.environ',{'TELEGRAM_EDUCATION_CHANNEL':''}):
            self.assertEqual(storage.claim_next('telegram','slot')['id'],job['id'])
    def test_claim_records_selected_destination(self):
        self.add_item('Fellowship','A leadership fellowship')
        item=storage.claim_next('telegram','slot')
        self.assertEqual(item['publication_destination'],'@education_channel')
        self.assertEqual(storage.get_publications()[0]['destination'],'@education_channel')
    def test_sender_uses_claimed_destination(self):
        self.add_item('Scholarship','A scholarship for students')
        with patch('publish.attachment_image',return_value=(b'image','image/jpeg','image.jpg')),patch('publish.send_telegram',return_value='77') as send:
            self.assertIn('posted',publish.publish_one('telegram','slot'))
        self.assertEqual(send.call_args.kwargs['channel'],'@education_channel')
    def test_same_channel_rejected(self):
        with patch.dict('os.environ',{'TELEGRAM_EDUCATION_CHANNEL':'@GENERAL_CHANNEL'}):
            with self.assertRaises(ValueError):telegram_routes()
    def test_roundups_isolate_actual_destination_and_preserve_old_posts(self):
        scholarship=self.add_item('Scholarship','A scholarship for students')
        job=self.add_item('Job','A distinct engineering role')
        # Simulate scholarship already published in general before routing existed.
        with storage.db() as c:
            for item,slot,remote in ((scholarship,'old','101'),(job,'job','102')):
                c.execute("INSERT INTO publications(opportunity_id,platform,slot_key,status,remote_id,created_at,updated_at,destination) VALUES(?,'telegram',?,'posted',?,'2026-10-16','2026-10-16','@general_channel')",(item['id'],slot,remote))
        fellowship=self.add_item('Fellowship','A global science fellowship')
        storage.claim_next('telegram','education');storage.set_publication(fellowship['id'],'telegram','posted','201')
        roundup.sync_roundup_destination()
        now=datetime(2026,10,16,tzinfo=roundup.TZ)
        _,general,n=roundup.build_roundup(now,'@general_channel')
        _,education,m=roundup.build_roundup(now,'@education_channel')
        self.assertEqual((n,m),(2,1))
        self.assertIn('general_channel/101',general);self.assertNotIn('education_channel/101',education)
        self.assertIn('education_channel/201',education);self.assertNotIn('science fellowship',general)
    def test_education_rename_does_not_move_general_history(self):
        self.add_item('Fellowship','A science fellowship opportunity')
        storage.claim_next('telegram','education');roundup.sync_roundup_destination()
        with patch.dict('os.environ',{'TELEGRAM_EDUCATION_CHANNEL':'@renamed_education'}):
            roundup.sync_roundup_destination()
        self.assertEqual(storage.get_publications()[0]['destination'],'@renamed_education')
    def test_separate_weekly_guards_send_to_both_channels(self):
        for category,title,remote in [('Job','A distinct engineering role','101'),('Fellowship','A science fellowship opportunity','201')]:
            item=self.add_item(category,title);storage.claim_next('telegram',remote);storage.set_publication(item['id'],'telegram','posted',remote)
        now=datetime(2026,10,12,8,tzinfo=roundup.TZ)
        with patch('roundup.enabled',return_value=True),patch('roundup.env',side_effect=lambda key: 'token' if key=='TELEGRAM_BOT_TOKEN' else ''),patch('publish.send_telegram_text',return_value='999') as send:
            result=roundup.publish_roundup(now)
            self.assertEqual(send.call_count,2)
            self.assertEqual({x.kwargs['channel'] for x in send.call_args_list},{'@general_channel','@education_channel'})
            roundup.publish_roundup(now);self.assertEqual(send.call_count,2)
