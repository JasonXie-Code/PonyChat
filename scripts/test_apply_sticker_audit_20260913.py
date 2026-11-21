"""Exercise metadata update, deleted-row protection, and conflict-safe rollback."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class AuditTest(unittest.TestCase):
    def test_update_and_rollback_preserve_concurrent_edits(self):
        script = Path(__file__).with_name('apply_sticker_audit_20260913.py')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / 'test.db'
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE media_assets (id TEXT PRIMARY KEY, category TEXT, name TEXT, '
                         'intro TEXT, detail TEXT, image_text TEXT, emotions TEXT, custom_tags TEXT, '
                         'intensity TEXT, age_rating TEXT, file_data BLOB)')
            original, proposal = [], []
            for i in range(3):
                row = dict(id=str(i),category='emoji',name='old',intro='old',detail='old',
                           image_text='',emotions='[]',custom_tags='[]',intensity='mild',age_rating='all')
                conn.execute('INSERT INTO media_assets VALUES (?,?,?,?,?,?,?,?,?,?,?)', [*row.values(),b'image'])
                original.append(dict(row,index=i,sha256=hashlib.sha256(b'image').hexdigest()))
                proposal.append(dict(row,index=i,name='new',intro='new',detail='new',
                                     emotions=['happy'],custom_tags=[]))
            conn.execute("UPDATE media_assets SET detail='concurrent' WHERE id='1'")
            conn.execute("DELETE FROM media_assets WHERE id='2'")
            conn.commit()
            for name, data in [('before.json',original),('proposal.json',proposal)]:
                (root/name).write_text(json.dumps(data),encoding='utf-8')
            def run(*args):
                return subprocess.run([sys.executable,str(script),'--db',str(db),
                                       '--audit-dir',str(root),*args],capture_output=True,text=True,check=True)
            run()
            self.assertEqual(conn.execute("SELECT name FROM media_assets WHERE id='0'").fetchone()[0],'old')
            run('--apply')
            result=json.loads((root/'applied.json').read_text(encoding='utf-8'))
            self.assertEqual([len(result[k]) for k in ('updated','conflicts','missing')],[1,1,1])
            self.assertEqual(conn.execute("SELECT file_data FROM media_assets WHERE id='0'").fetchone()[0],b'image')
            self.assertEqual(conn.execute("SELECT detail FROM media_assets WHERE id='1'").fetchone()[0],'concurrent')
            conn.execute("UPDATE media_assets SET name='later-edit' WHERE id='0'")
            conn.commit()
            run('--rollback')
            self.assertEqual(conn.execute("SELECT name FROM media_assets WHERE id='0'").fetchone()[0],'later-edit')
            conn.execute("UPDATE media_assets SET name='new' WHERE id='0'")
            conn.commit()
            run('--rollback')
            self.assertEqual(conn.execute("SELECT name FROM media_assets WHERE id='0'").fetchone()[0],'old')
            self.assertEqual(conn.execute('SELECT count(*) FROM media_assets').fetchone()[0],2)
            conn.close()


if __name__ == '__main__':
    unittest.main()
