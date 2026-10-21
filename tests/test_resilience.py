import base64
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from cryptography.fernet import Fernet
import cloud_state as state

class Store:
    def __init__(self): self.files={}; self.writes=0
    def api(self,path,method='GET',data=None):
        if path=='repos/o/r':return {'private':True}
        if '/git/blobs/' in path:
            sha=path.rsplit('/',1)[1]
            return {'content':base64.b64encode(next(b for b in self.files.values() if self.sha(b)==sha)).decode()}
        key=path.split('/contents/',1)[1].split('?')[0]
        if method=='GET':
            if key not in self.files:raise state.StateAPIError(404,'missing')
            return {'sha':self.sha(self.files[key])}
        if method=='PUT':
            old=self.files.get(key)
            if old and data.get('sha')!=self.sha(old):raise state.StateAPIError(409,'conflict')
            self.files[key]=base64.b64decode(data['content']);self.writes+=1
            return {'content':{'sha':self.sha(self.files[key])}}
        raise AssertionError(path)
    @staticmethod
    def sha(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()

class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.key=Fernet.generate_key().decode();self.store=Store()
        self.env=patch.dict(os.environ,STATE_REPOSITORY='o/r',STATE_ENCRYPTION_KEY=self.key)
        self.env.start();self.r=patch.object(state,'ROOT',self.root);self.r.start()
        state.repo.cache_clear()
    def tearDown(self):
        self.r.stop();self.env.stop();self.tmp.cleanup();state.repo.cache_clear()
    def archive(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('opportunities.db',b'preserved database');z.writestr('media/original.jpg',b'image')
        return out.getvalue()
    def seed_existing(self,plain):
        binary=Fernet(self.key.encode()).encrypt(plain)
        self.store.files['state.enc']=binary
        state.write_meta(self.store.sha(binary),hashlib.sha256(plain).hexdigest())
    def test_legacy_restore_and_skip_unchanged(self):
        plain=self.archive();self.seed_existing(plain)
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=plain):
            state.restore();state.save()
        self.assertEqual((self.root/'data/opportunities.db').read_bytes(),b'preserved database')
        self.assertEqual(self.store.writes,0)
    def test_large_archive_roundtrip_preserves_all_images(self):
        old=self.archive();self.seed_existing(old)
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('opportunities.db',b'new database');z.writestr('media/photo.jpg',os.urandom(2000))
        plain=out.getvalue()
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=plain),patch.object(state,'MAX_BYTES',200),patch.object(state,'PART_BYTES',300):
            state.save();self.assertGreater(len(self.store.files),2)
            state.restore()
        self.assertEqual((self.root/'data/opportunities.db').read_bytes(),b'new database')
        self.assertEqual((self.root/'data/media/photo.jpg').stat().st_size,2000)
    def test_media_buckets_reused_after_database_changes(self):
        self.seed_existing(self.archive())
        photo=os.urandom(4_100_000)
        def archive(db):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                state.write_archive(z,'opportunities.db',db)
                state.write_archive(z,'media/photo.jpg',photo)
            return out.getvalue()
        first=archive(b'first database')
        second=archive(b'second database')
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=first):
            state.save()
        manifest=Fernet(self.key.encode()).decrypt(self.store.files['state.enc'])
        self.assertEqual(json.loads(manifest)['format'],'publisher-media-v2')
        writes=self.store.writes
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=second):
            state.save()
            self.assertEqual(self.store.writes,writes+1)
            state.restore()
            state.save()
        self.assertEqual((self.root/'data/media/photo.jpg').read_bytes(),photo)
        self.assertEqual((self.root/'data/opportunities.db').read_bytes(),b'second database')
        self.assertEqual(self.store.writes,writes+1)

    def test_archive_above_old_25mb_limit_is_durable(self):
        self.seed_existing(self.archive())
        out=io.BytesIO()
        photo=os.urandom(20_000_000)
        with zipfile.ZipFile(out,'w') as z:
            state.write_archive(z,'opportunities.db',b'durable new opportunities')
            state.write_archive(z,'media/large.jpg',photo)
        plain=out.getvalue()
        self.assertGreater(len(Fernet(self.key.encode()).encrypt(plain)),25_000_000)
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=plain):
            state.save()
            self.assertLess(len(self.store.files['state.enc']),25_000_000)
            state.restore()
        self.assertEqual((self.root/'data/media/large.jpg').read_bytes(),photo)

    def test_interrupted_parts_keep_previous_root(self):
        old=self.archive();self.seed_existing(old);root=self.store.files['state.enc']
        original=self.store.api
        def fail(path,method='GET',data=None):
            if method=='PUT' and 'state-parts/' in path:raise RuntimeError('offline')
            return original(path,method,data)
        with patch.object(state,'api',side_effect=fail),patch.object(state,'pack',return_value=old+b'extra'),patch.object(state,'MAX_BYTES',20),patch.object(state,'PART_BYTES',30):
            with self.assertRaises(RuntimeError):state.save()
        self.assertEqual(self.store.files['state.enc'],root)
    def test_concurrent_writer_is_never_overwritten(self):
        self.seed_existing(self.archive());self.store.files['state.enc']=b'other writer'
        with patch.object(state,'api',side_effect=self.store.api):
            with self.assertRaisesRegex(RuntimeError,'another writer'):state.save()
        self.assertEqual(self.store.writes,0)
    def test_corrupt_part_stops_restore(self):
        old=self.archive();self.seed_existing(old)
        with patch.object(state,'api',side_effect=self.store.api),patch.object(state,'pack',return_value=old+b'extra'),patch.object(state,'MAX_BYTES',200),patch.object(state,'PART_BYTES',300):
            state.save()
            part=next(k for k in self.store.files if k.startswith('state-parts/'))
            self.store.files[part]+=b'bad'
            with self.assertRaisesRegex(RuntimeError,'integrity'):state.restore()
        self.assertFalse((self.root/'.cloud-restored').exists())
    def test_retry_only_transient_errors(self):
        state.repo.cache_clear()
        response=unittest.mock.MagicMock()
        response.__enter__.return_value=io.BytesIO(b'{"ok":true}')
        err=HTTPError('secret',503,'unavailable',{},io.BytesIO(b'error'))
        with patch.dict(os.environ,STATE_REPO_TOKEN='private'),patch.object(state,'urlopen',side_effect=[err,response]) as get,patch.object(state.time,'sleep'):
            self.assertTrue(state.api('test')['ok']);self.assertEqual(get.call_count,2)
        err=HTTPError('secret',403,'denied',{},io.BytesIO(b'permissions'))
        with patch.dict(os.environ,STATE_REPO_TOKEN='private'),patch.object(state,'urlopen',side_effect=err) as get:
            with self.assertRaisesRegex(state.StateAPIError,'access denied'):state.api('test')
            self.assertEqual(get.call_count,1)
    def test_conflict_with_unchanged_sha_retries(self):
        self.store.files['state.enc']=b'old';previous={'sha':self.store.sha(b'old')}
        original=self.store.api;calls=0
        def conflict(path,method='GET',data=None):
            nonlocal calls
            if method=='PUT':
                calls+=1
                if calls==1:raise state.StateAPIError(409,'conflict')
            return original(path,method,data)
        with patch.object(state,'api',side_effect=conflict),patch.object(state.time,'sleep'):
            state.put_entry('o/r','state.enc',b'new',previous)
        self.assertEqual(self.store.files['state.enc'],b'new')
    def test_content_changed_conflict_aborts(self):
        self.store.files['state.enc']=b'other'
        with patch.object(state,'api',side_effect=self.store.api):
            with self.assertRaisesRegex(RuntimeError,'concurrently'):state.put_entry('o/r','state.enc',b'new',{'sha':'old'})
        self.assertEqual(self.store.files['state.enc'],b'other')


class CollectionRecoveryTests(unittest.TestCase):
    def test_failed_collection_retries_without_advancing_success_timer(self):
        import time
        import cloud_run
        import storage
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage,'DATA_DIR',Path(tmp)), patch.object(storage,'DB_PATH',Path(tmp)/'test.db'):
            storage.init_db()
            last=time.time()-8000
            storage.set_state('cloud:last_collection_success',str(last))
            storage.set_state('cloud:last_collection_attempt',str(time.time()))
            with patch.object(cloud_run,'config',return_value={'collect_every_minutes':120}), patch.object(cloud_run,'collect_all',side_effect=TimeoutError) as collect, patch.object(cloud_run,'sync_roundup_destination'), patch.object(cloud_run,'restore_requested_aixbio'), patch.object(cloud_run,'recover_missing_application_links'), patch.object(cloud_run,'auto_approve',return_value=0), patch.object(cloud_run,'report_queues'), patch.object(cloud_run,'enabled',return_value=False):
                cloud_run.run();cloud_run.run()
            self.assertEqual(collect.call_count,2)
            self.assertEqual(float(storage.get_state('cloud:last_collection_success')),last)


class MessageIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_message_is_deferred_other_messages_continue_and_retry(self):
        import sys,types
        from datetime import datetime,timezone
        from unittest.mock import AsyncMock
        import collectors,storage
        first=True
        msg=lambda id:types.SimpleNamespace(id=id,date=datetime.now(timezone.utc),raw_text='Valid opportunity',entities=[],text_html='')
        class Client:
            def __init__(self,*a,**kw):pass
            async def connect(self):pass
            async def disconnect(self):pass
            async def is_user_authorized(self):return True
            async def get_entity(self,ch):return types.SimpleNamespace(id=7,username='source')
            async def get_messages(self,entity,ids):return [msg(id) for id in ids]
            async def iter_messages(self,entity,**kw):
                if kw.get('min_id',0)<102:
                    for id in (101,102):yield msg(id)
        def store(raw,key,*args,**kwargs):
            nonlocal first
            if key.endswith(':101') and first:
                first=False
                raise ValueError('bad content')
            return True
        with tempfile.TemporaryDirectory() as tmp,patch.object(storage,'DATA_DIR',Path(tmp)),patch.object(storage,'DB_PATH',Path(tmp)/'test.db'):
            storage.init_db()
            cfg={'telegram_channels':['source'],'max_items_per_source':30}
            with patch.dict(sys.modules,{'telethon':types.SimpleNamespace(TelegramClient=Client)}),patch.object(collectors,'refresh_pending_source_dates',new_callable=AsyncMock),patch.object(collectors,'env',side_effect=lambda key:'1' if key=='TELEGRAM_API_ID' else 'hash'),patch.object(collectors,'store',side_effect=store),patch.object(collectors,'source_exists',return_value=False),patch.object(collectors,'source_image',new_callable=AsyncMock,return_value=''):
                self.assertEqual(await collectors.fetch_telegram_async(cfg),1)
                self.assertEqual(storage.get_state('telegram:retry_ids:7'),'[101]')
                self.assertEqual(storage.get_state('telegram:last_id:7'),'102')
                self.assertEqual(await collectors.fetch_telegram_async(cfg),1)
                self.assertEqual(storage.get_state('telegram:retry_ids:7'),'[]')
                self.assertEqual(storage.get_state('telegram:last_id:7'),'102')

if __name__=='__main__':unittest.main()
