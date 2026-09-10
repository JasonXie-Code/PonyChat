"""Exercise retention decisions on a small isolated SQLite database."""
import sqlite3
import unittest

from retain_local_users import fingerprint, predicates, should_remove_file


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,avatar TEXT);
            INSERT INTO users VALUES(1,'Jason','kept.jpg'),(73,'System',''),(4,'other','removed.jpg');
            CREATE TABLE characters(id TEXT,user_id INTEGER,data TEXT);
            INSERT INTO characters VALUES('keep',1,'{"image":"kept.png"}'),('orphan',999,'');
            CREATE TABLE conversations(id TEXT,user_id INTEGER);
            INSERT INTO conversations VALUES('keep',1),('remove',4);
            CREATE TABLE messages(conversation_id TEXT,content TEXT);
            INSERT INTO messages VALUES('keep','unchanged'),('remove','private'),('orphan','orphan');
            CREATE TABLE agent_memory_heads(entry_id TEXT,username TEXT);
            INSERT INTO agent_memory_heads VALUES('keep','Jason'),('remove','other');
            CREATE TABLE agent_memory_entries(entry_id TEXT,username TEXT);
            CREATE TABLE agent_memory_versions(entry_id TEXT,content TEXT);
            INSERT INTO agent_memory_versions VALUES('keep','kept memory'),('remove','other memory');
            CREATE TABLE avatars(filename TEXT,data BLOB);
            INSERT INTO avatars VALUES('kept.jpg',X'1234'),('removed.jpg',X'5678');
            CREATE TABLE chat_images(filename TEXT,data BLOB);
            INSERT INTO chat_images VALUES('kept.png',X'1234'),('removed.png',X'5678');
            CREATE TABLE media_assets(uploader_id INTEGER,name TEXT);
            INSERT INTO media_assets VALUES(NULL,'global'),(1,'kept'),(4,'removed');
            CREATE TABLE normal_scene_state(username TEXT,scene TEXT);
            INSERT INTO normal_scene_state VALUES('Jason','kept'),('jason','wrong case'),('deleted','orphan');
            CREATE TABLE deletion_audits(username TEXT,detail TEXT);
            INSERT INTO deletion_audits VALUES('Jason','also remove'),('other','remove');
            CREATE TABLE hall_characters(id INTEGER,publisher_username TEXT);
            INSERT INTO hall_characters VALUES(1,'System'),(2,'other');
            CREATE TABLE hall_character_likes(username TEXT,hall_id INTEGER);
            INSERT INTO hall_character_likes VALUES('Jason',1),('Jason',2),('other',1);
        """)

    def tearDown(self):
        self.db.close()

    def kept(self, table):
        condition = predicates(self.db)[table]
        return self.db.execute(f'SELECT * FROM "{table}" WHERE {condition}').fetchall()

    def test_exact_account_names_and_orphan_ownership(self):
        self.assertEqual(self.kept('normal_scene_state'), [('Jason', 'kept')])
        self.assertEqual(len(self.kept('characters')), 1)

    def test_conversations_and_memory_versions_follow_retained_owners(self):
        self.assertEqual(self.kept('messages'), [('keep', 'unchanged')])
        self.assertEqual(self.kept('agent_memory_versions'), [('keep', 'kept memory')])

    def test_keep_referenced_blobs_and_global_media(self):
        self.assertEqual(self.kept('avatars'), [('kept.jpg', b'\x12\x34')])
        self.assertEqual(self.kept('chat_images'), [('kept.png', b'\x12\x34')])
        self.assertEqual(self.kept('media_assets'), [(None, 'global'), (1, 'kept')])

    def test_logs_are_removed_for_both_retained_and_deleted_accounts(self):
        self.assertEqual(self.kept('deletion_audits'), [])

    def test_likes_do_not_reference_removed_hall_characters(self):
        self.assertEqual(self.kept('hall_character_likes'), [('Jason', 1)])

    def test_unknown_schema_blocks_cleanup(self):
        self.db.execute('CREATE TABLE unclassified(payload TEXT)')
        with self.assertRaisesRegex(RuntimeError, 'Unclassified table'):
            predicates(self.db)

    def test_fingerprint_detects_changed_content(self):
        before = fingerprint(self.db, 'messages', "conversation_id='keep'")
        self.db.execute("UPDATE messages SET content='changed' WHERE conversation_id='keep'")
        self.assertNotEqual(before, fingerprint(self.db, 'messages', "conversation_id='keep'"))

    def test_stale_manifest_log_flags_do_not_delete_knowledge_data(self):
        for path in ['Backend/data/mlp/tags.jsonl', 'Backend/data/mlp/tags_test.jsonl',
                     'Backend/data/mlp/pages/Dishwater Slog.txt',
                     'Backend/data/mlp/pages/Fictional chronology.txt']:
            with self.subTest(path=path):
                self.assertFalse(should_remove_file({'path': path, 'log': True}))
        self.assertTrue(should_remove_file({'path': 'var/local-stack/supervisor.log', 'log': True}))
        self.assertFalse(should_remove_file({'path': 'var/local-stack/supervisor.log', 'log': False}))

    def test_recovery_removal_keeps_users_but_honors_explicit_character_removal(self):
        cases = [('other/keep.json', True), ('Jason/keep.json', False),
                 ('System/keep.json', False), ('Jason/removed-character.json', True)]
        for name, expected in cases:
            with self.subTest(name=name):
                row = {'path': 'var/recovery_snapshots/galgame/' + name, 'log': False}
                self.assertEqual(should_remove_file(row, ('removed-character',)), expected)

    def test_explicit_character_removal_includes_related_conversations_and_memory(self):
        self.db.execute('ALTER TABLE conversations ADD COLUMN character_id TEXT')
        self.db.execute("UPDATE conversations SET character_id='orphan' WHERE id='keep'")
        for table in ['agent_memory_heads', 'agent_memory_entries', 'normal_scene_state']:
            self.db.execute(f'ALTER TABLE {table} ADD COLUMN character_id TEXT')
            self.db.execute(f"UPDATE {table} SET character_id='orphan' WHERE username='Jason'")
        choices = predicates(self.db, ('orphan',))
        for table in ['messages', 'agent_memory_versions', 'agent_memory_heads', 'normal_scene_state']:
            count = self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE {choices[table]}').fetchone()[0]
            self.assertEqual(count, 0, table)
        self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM users WHERE {choices['users']}").fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
