import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from opportunity_dates import parse_deadline,deadline_problem,source_is_recent,TZ
from routing import opportunity_category,telegram_destination
from opportunity_quality import publication_block_reason
import test_cloud, storage, collectors, roundup

NOW=datetime(2026,10,17,21,0,tzinfo=TZ)

class DeadlineTests(unittest.TestCase):
    def test_explicit_past_deadline_not_saved_is_still_blocked(self):
        self.assertTrue(deadline_problem({'deadline':'','raw_text':'Deadline: 15 October 2026'},NOW))
    def test_source_contradicts_wrong_future_saved_deadline(self):
        self.assertTrue(deadline_problem({'deadline':'2027-10-15','raw_text':'Deadline: October 15, 2026'},NOW))
    def test_today_is_not_expired_and_future_is_allowed(self):
        for value in ('2026-10-17','2026-10-18'):
            self.assertFalse(deadline_problem({'deadline':value},NOW))
    def test_yearless_date_uses_original_post_year_without_rolling_forward(self):
        opp={'source_posted_at':'2026-10-16T10:00:00+00:00','raw_text':'Deadline: September 30'}
        self.assertTrue(deadline_problem(opp,NOW))
    def test_numeric_dates_and_ambiguous_date(self):
        self.assertEqual(parse_deadline('Closing date: 15/10/2026'),'2026-10-15')
        self.assertTrue(deadline_problem({'raw_text':'Deadline: 10/11/2026'},NOW))
    def test_unreadable_explicit_deadline_not_treated_as_rolling(self):
        self.assertTrue(deadline_problem({'raw_text':'Deadline: see image'},NOW))
        self.assertFalse(deadline_problem({'raw_text':'Deadline: Rolling applications'},NOW))
    def test_group_with_any_expired_deadline_is_held(self):
        self.assertTrue(deadline_problem({'raw_text':'Deadline: 16 October 2026\nDeadline: 20 October 2026'},NOW))
    def test_invalid_date_is_held(self):
        self.assertTrue(deadline_problem({'deadline':'2026-02-30'},NOW))
    def test_five_day_boundary(self):
        self.assertTrue(source_is_recent(NOW-timedelta(days=5),NOW))
        self.assertFalse(source_is_recent(NOW-timedelta(days=5,seconds=1),NOW))
        self.assertFalse(source_is_recent(None,NOW))

class StrongRoutingTests(unittest.TestCase):
    def test_reported_university_titles_route_to_education_despite_wrong_category(self):
        titles=['UNIVERSITY OF MELBOURNE HUMAN RIGHTS SCHOLARSHIP 2026 – NOW OPEN',
                'University of bocconi - admission for 2027/2028 AY are open now!',
                'University of Padova - admission for 2027/2028 AY are open now!',
                'Here are Czech Republic universities with low tuition fees for 2027/2028']
        with patch.dict('os.environ',{'TELEGRAM_TARGET_CHANNEL':'@general_channel','TELEGRAM_EDUCATION_CHANNEL':'@education_channel'}):
            for title in titles:
                self.assertEqual(telegram_destination({'title':title,'category':'Other'}),'@education_channel')
    def test_actual_university_job_stays_general(self):
        self.assertEqual(opportunity_category({'title':'University of Example is hiring a lecturer','category':'Scholarship'}),'Job')
    def test_incidental_background_internship_not_override_scholarship_title(self):
        self.assertEqual(opportunity_category({'title':'Masters scholarship in law','category':'Internship','raw_text':'Prior internship experience preferred.'}),'Scholarship')

class PendingMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_queue_metadata_backfill_does_not_create_publication(self):
        import types
        fixture=test_cloud.CloudTests();fixture.setUp()
        try:
            storage.add_opportunity({'source_key':'telegram:7:12','title':'Research vacancy','organization':'Institute','apply_url':'https://example.org/job'})
            stamp=datetime.now(timezone.utc)-timedelta(days=8)
            class Client:
                async def get_messages(self,entity,ids):return [types.SimpleNamespace(id=12,date=stamp)]
            await collectors.refresh_pending_source_dates(Client(),types.SimpleNamespace(id=7))
            item=storage.get_opportunities()[0]
            self.assertEqual(item['source_posted_at'],stamp.isoformat())
            self.assertTrue(publication_block_reason(item))
            self.assertFalse(storage.get_publications())
        finally:fixture.tearDown()

class RoundupEmptyTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    def test_empty_both_channels_never_send(self):
        with patch('roundup.enabled',return_value=True),patch('roundup.env',return_value='token'),patch('publish.send_telegram_text') as send:
            self.assertEqual(roundup.publish_roundup(datetime(2026,10,19,8,tzinfo=TZ)),'')
            send.assert_not_called()

class CollectionWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_message_skipped_before_image_or_storage(self):
        import sys,types
        from unittest.mock import AsyncMock
        fixture=test_cloud.CloudTests();fixture.setUp()
        try:
            now=datetime.now(timezone.utc)
            old=types.SimpleNamespace(id=10,date=now-timedelta(days=6),raw_text='Old scholarship',entities=[])
            fresh=types.SimpleNamespace(id=11,date=now-timedelta(days=1),raw_text='New scholarship',entities=[],text_html='')
            kwargs={}
            class Client:
                def __init__(self,*a,**k):pass
                async def connect(self):pass
                async def disconnect(self):pass
                async def is_user_authorized(self):return True
                async def get_entity(self,ch):return types.SimpleNamespace(id=7,username='source')
                async def iter_messages(self,entity,**kw):
                    kwargs.update(kw)
                    for msg in (old,fresh):yield msg
            with patch.dict(sys.modules,{'telethon':types.SimpleNamespace(TelegramClient=Client)}),patch('collectors.env',side_effect=lambda k:'1' if k=='TELEGRAM_API_ID' else 'hash'),patch('collectors.store',return_value=True) as store,patch('collectors.source_image',new_callable=AsyncMock,return_value='') as image:
                count=await collectors.fetch_telegram_async({'telegram_channels':['source'],'max_items_per_source':30})
            self.assertEqual(count,1)
            self.assertEqual(store.call_count,1)
            self.assertEqual(store.call_args.args[1],'telegram:7:11')
            self.assertEqual(store.call_args.kwargs['fields']['source_posted_at'],fresh.date.isoformat())
            self.assertEqual(image.await_count,1)
            self.assertEqual(storage.get_state('telegram:last_id:7'),'11')
            self.assertIn('offset_date',kwargs)
        finally:fixture.tearDown()

class ExpiredQueueTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    def test_old_raw_deadline_blocks_preapproved_queue_record(self):
        storage.add_opportunity({'source_key':'legacy','title':'Scholarship at Example Institute','organization':'Example Institute','category':'Other','deadline':'','raw_text':'Deadline: 15 October 2020','apply_url':'https://example.org/old'})
        item=storage.get_opportunities()[0]
        storage.update_opportunity(item['id'],{},status='approved')
        self.assertIsNone(storage.claim_next('telegram','expired',destination='@education_channel'))
        self.assertFalse(storage.get_publications())
