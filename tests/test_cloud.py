import io, os, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
import storage, cloud_run, cloud_state, collectors
from message_layout import telegram_layout, visible_units

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.patches=[patch.object(storage,'DB_PATH',self.root/'data/opportunities.db'),patch.object(storage,'DATA_DIR',self.root/'data'),patch.object(cloud_state,'ROOT',self.root)]
        for p in self.patches:p.start()
        storage.init_db()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def add(self,title,url,deadline=''):
        storage.add_opportunity(dict(source_key=title,title=title,apply_url=url,description='Useful factual benefits',raw_text='Useful facts',deadline=deadline))
    def test_encrypted_state(self):
        self.add('A distinct test opportunity','https://example.org/a')
        key=Fernet.generate_key()
        with patch.dict(os.environ,{'STATE_ENCRYPTION_KEY':key.decode()}):binary=cloud_state.pack()
        self.assertNotIn(b'Useful facts',binary)
        archive=zipfile.ZipFile(io.BytesIO(Fernet(key).decrypt(binary)))
        self.assertIn('opportunities.db',archive.namelist())
        with self.assertRaises(Exception):Fernet(Fernet.generate_key()).decrypt(binary)
    def test_approval_filters(self):
        self.add('Valid scholarship opportunity','https://example.org/a','2099-01-01')
        self.add('Expired training opportunity','https://example.org/b','2000-01-01')
        self.add('Missing link workshop opportunity','')
        with patch('cloud_run.config',return_value={'cloud_auto_approve':1}):self.assertEqual(cloud_run.auto_approve(),1)
        self.assertEqual(len(storage.get_opportunities('approved')),1)
    def test_public_fanout(self):
        cfg=dict(rss_feeds=['a','b'],greenhouse_boards=['c'],lever_sites=[],public_source_workers=3)
        def single(one):
            self.assertEqual(sum(len(one[k]) for k in ('rss_feeds','greenhouse_boards','lever_sites')),1)
            return 2
        with patch('collectors._fetch_public_sources_serial',side_effect=single):self.assertEqual(collectors.fetch_public_sources(cfg),6)
    def test_state_failure_prevents_send(self):
        with patch('cloud_run.config',return_value={'cloud_work_seconds':300}),patch('cloud_run.collect_all',return_value={}),patch('cloud_run.auto_approve',return_value=0),patch('cloud_run.enabled',return_value=True),patch('publish.send_telegram') as send:
            with self.assertRaises(RuntimeError):cloud_run.run(checkpoint=lambda:(_ for _ in ()).throw(RuntimeError('unavailable')))
            send.assert_not_called()
    def test_captions(self):
        text='<b>Title</b>\n\nShort facts'
        self.assertEqual(telegram_layout(text),(text,[]))
        text='<b>Scholarship</b>\n<b>Example</b>\n📅 <b>Deadline: 2099-01-01</b>\n'+'\n'.join('Useful detail '+str(i) for i in range(100))+'\n<a href="https://example.org/apply">Apply here</a>'
        caption,rest=telegram_layout(text)
        self.assertLessEqual(visible_units(caption),1024);self.assertFalse(rest)
        self.assertIn('2099-01-01',caption);self.assertIn('https://example.org/apply',caption)
    def test_restore_failure_closed(self):
        with patch('cloud_state.repo',return_value='owner/repo'),patch('cloud_state.api',side_effect=RuntimeError('network')):
            with self.assertRaises(RuntimeError):cloud_state.restore()
        self.assertFalse((self.root/'.cloud-restored').exists())
    def test_six_stable_slots(self):
        slots=[]
        with patch('cloud_run.config',return_value={'cloud_work_seconds':300,'cloud_batch_size':6}),patch('cloud_run.collect_all',return_value={}),patch('cloud_run.auto_approve',return_value=0),patch('cloud_run.enabled',return_value=True),patch('publish.allowed_platforms',return_value=['telegram']),patch('publish.publish_one',side_effect=lambda platform,slot:slots.append(slot) or 'posted'),patch('cloud_run.publish_roundup',return_value=''):
            cloud_run.run()
        self.assertEqual(len(slots),6);self.assertEqual(len(set(slots)),6)

class TelegramCursorTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_reads_oldest_unseen_and_advances_cursor(self):
        import sys, types
        calls={}
        class Message:
            raw_text='A useful new opportunity'; entities=[]
            def __init__(self,n): self.id=n
        class Client:
            def __init__(self,*a,**kw):pass
            async def connect(self):pass
            async def disconnect(self):pass
            async def is_user_authorized(self):return True
            async def get_entity(self,ch):return types.SimpleNamespace(id=7,username='source')
            async def iter_messages(self,entity,**kwargs):
                calls.update(kwargs)
                for n in (101,102):yield Message(n)
        with patch.dict(sys.modules,{'telethon':types.SimpleNamespace(TelegramClient=Client)}),patch('collectors.env',side_effect=lambda k:'1' if k=='TELEGRAM_API_ID' else 'hash'),patch('collectors.get_state',return_value='100'),patch('collectors.set_state') as state,patch('collectors.source_exists',return_value=True),patch('collectors.store',return_value=False):
            result=await collectors.fetch_telegram_async({'telegram_channels':['source'],'max_items_per_source':2})
        self.assertTrue(calls['reverse']);self.assertEqual(calls['min_id'],100)
        state.assert_called_once_with('telegram:last_id:7','102')

class PublicStateTests(unittest.TestCase):
    def test_requires_explicit_state_repository(self):
        with patch.dict(os.environ,{'STATE_REPOSITORY':''}):
            with self.assertRaises(RuntimeError):cloud_state.repo()
    def test_refuses_public_state(self):
        with patch.dict(os.environ,{'STATE_REPOSITORY':'owner/state'}),patch('cloud_state.api',return_value={'private':False}):
            with self.assertRaises(RuntimeError):cloud_state.repo()
    def test_accepts_private_state(self):
        with patch.dict(os.environ,{'STATE_REPOSITORY':'owner/state'}),patch('cloud_state.api',return_value={'private':True}):
            self.assertEqual(cloud_state.repo(),'owner/state')

class DuplicateEnrichmentTests(unittest.TestCase):
    setUp = CloudTests.setUp
    tearDown = CloudTests.tearDown
    add = CloudTests.add
    def test_duplicate_fills_missing_image_and_keeps_one_record(self):
        self.add('Marketing Intern Opportunity','https://example.org/unique')
        value=dict(source_key='other-channel',title='Marketing Intern Opportunity',apply_url='https://example.org/unique',image_path='flyer.jpg')
        self.assertFalse(storage.add_opportunity(value))
        rows=storage.get_opportunities();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['image_path'],'flyer.jpg')
        self.assertTrue(storage.source_exists('other-channel'))
    def test_published_duplicate_never_changes_published_record(self):
        self.add('Marketing Intern Opportunity','https://example.org/unique')
        oid=storage.get_opportunities()[0]['id'];storage.update_opportunity(oid,{},status='approved')
        storage.claim_next('telegram','test');storage.set_publication(oid,'telegram','posted','123')
        self.assertFalse(storage.add_opportunity(dict(source_key='other-channel',title='Marketing Intern Opportunity',apply_url='https://example.org/unique',image_path='other.jpg')))
        self.assertEqual(storage.get_opportunity(oid)['image_path'],'')
