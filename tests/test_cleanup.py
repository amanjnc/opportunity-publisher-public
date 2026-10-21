import base64
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
import cloud_state as state

class CleanupTests(unittest.TestCase):
    def test_local_keeps_only_archived_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); media=root/'data/media';media.mkdir(parents=True)
            (media/'queued.jpg').write_bytes(b'keep');(media/'posted.jpg').write_bytes(b'remove')
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:z.writestr('media/queued.jpg',b'keep')
            with patch.object(state,'ROOT',root):state.cleanup_local_media(out.getvalue())
            self.assertTrue((media/'queued.jpg').exists());self.assertFalse((media/'posted.jpg').exists())

    def test_gc_retains_both_checkpoints_and_uses_nonforce_update(self):
        active='state-media/'+'a'*64+'.enc'; recovery='state-media/'+'b'*64+'.enc';old='state-media/'+'c'*64+'.enc'
        paths=['state.enc','state.previous.enc',active,recovery,old,'unrelated.enc']
        calls=[]
        def api(path,method='GET',data=None):
            calls.append((path,method,data))
            if method=='GET' and '/git/ref/' in path:return {'object':{'sha':'head'}}
            if method=='GET' and '/git/commits/' in path:return {'tree':{'sha':'tree'}}
            if method=='GET' and '/git/trees/' in path:return {'tree':[{'path':p,'sha':p,'type':'blob'} for p in paths]}
            if method=='POST':return {'sha':'new'}
            return {}
        def refs(name,entry):return {active} if entry['path']=='state.enc' else {recovery}
        with patch.object(state,'get_entry',return_value=None),patch.object(state,'api',side_effect=api),patch.object(state,'checkpoint_parts',side_effect=refs):state.cleanup_remote_media('o/r')
        changes=next(data['tree'] for path,method,data in calls if path.endswith('/git/trees') and method=='POST')
        self.assertEqual([x['path'] for x in changes if x.get('sha','absent') is None],[old])
        self.assertEqual(calls[-1][2],{'sha':'new','force':False})

    def test_gc_refuses_cleanup_if_checkpoint_cannot_be_verified(self):
        paths=['state.enc','state.previous.enc']
        calls=[]
        def api(path,method='GET',data=None):
            calls.append(method)
            if '/git/ref/' in path:return {'object':{'sha':'head'}}
            if '/git/commits/' in path:return {'tree':{'sha':'tree'}}
            return {'tree':[{'path':p,'sha':p,'type':'blob'} for p in paths]}
        with patch.object(state,'get_entry',return_value=None),patch.object(state,'api',side_effect=api),patch.object(state,'checkpoint_parts',side_effect=RuntimeError('corrupt')):
            with self.assertRaises(RuntimeError):state.cleanup_remote_media('o/r')
        self.assertNotIn('POST',calls)
