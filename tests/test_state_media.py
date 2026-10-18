import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from cloud_state import archived_images, compact_image


class StateMediaTests(unittest.TestCase):
    def test_cleanup_dedup_preserves_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'media').mkdir()
            c = sqlite3.connect(':memory:')
            c.execute('CREATE TABLE opportunities(id INTEGER PRIMARY KEY,status TEXT,image_path TEXT,deadline TEXT)')
            c.execute('CREATE TABLE publications(opportunity_id INTEGER,platform TEXT,status TEXT)')
            for id, status, deadline in [(1,'approved','2099-01-01'),(2,'review',''),(3,'rejected',''),(4,'approved','2000-01-01'),(5,'approved','')]:
                name = f'{id}.jpg'
                (root / 'media' / name).write_bytes(b'identical photo')
                c.execute('INSERT INTO opportunities VALUES(?,?,?,?)',(id,status,name,deadline))
            c.execute("INSERT INTO publications VALUES(5,'telegram','posted')")
            c.commit()
            media = archived_images(c,root)
            self.assertEqual(list(media), ['1.jpg'])
            self.assertEqual(c.execute('SELECT image_path FROM opportunities WHERE id=2').fetchone()[0],'1.jpg')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0],5)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM publications').fetchone()[0],1)
            self.assertEqual(len(list((root/'media').iterdir())),5)

    def test_large_source_compressed_small_intact(self):
        image = Image.effect_noise((2200,2200),100).convert('RGB')
        out = io.BytesIO()
        image.save(out,'PNG')
        original = out.getvalue()
        result = compact_image(original)
        self.assertLess(len(result),len(original))
        with Image.open(io.BytesIO(result)) as restored:
            self.assertLessEqual(max(restored.size),1600)
        self.assertEqual(compact_image(b'small'),b'small')
        self.assertEqual(compact_image(b'x'*400001),b'x'*400001)
