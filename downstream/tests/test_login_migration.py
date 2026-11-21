"""Exercise the pinned admission export and import against SQLite fixtures."""

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "migrate_login.py"
spec = importlib.util.spec_from_file_location("migrate_login", FILE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@contextmanager
def connect(path):
    with closing(sqlite3.connect(path)) as db, db:
        yield db


class LoginTransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source.db"
        self.target = self.root / "target.db"
        self.bundle = self.root / "login.db"
        for path, revision in ((self.source, migration.SOURCE), (self.target, migration.TARGET)):
            with connect(path) as db:
                db.executescript("""
                    CREATE TABLE alembic_version(version_num TEXT);
                    CREATE TABLE user(id TEXT PRIMARY KEY, email TEXT, role TEXT, oauth TEXT, scim TEXT,
                        name TEXT, last_active_at INTEGER, created_at INTEGER, updated_at INTEGER, settings TEXT);
                    CREATE TABLE auth(id TEXT PRIMARY KEY, email TEXT, password TEXT, active INTEGER, session_stamp TEXT);
                    CREATE TABLE "group"(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,permissions TEXT,
                        description TEXT,created_at INTEGER,updated_at INTEGER);
                    CREATE TABLE group_member(id TEXT PRIMARY KEY,group_id TEXT,user_id TEXT,created_at INTEGER,updated_at INTEGER);
                    CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT,updated_at INTEGER);
                    CREATE TABLE chat(id TEXT);
                    CREATE TABLE file(id TEXT);
                """)
                db.execute("INSERT INTO alembic_version VALUES(?)", (revision,))
        self.hash = "$2b$12$" + "A" * 53
        with connect(self.source) as db:
            for ident, role, enabled in (("a", "admin", 1), ("b", "user", 1), ("c", "pending", 1), ("d", "user", 0)):
                email = ident + "@example.org"
                oauth = json.dumps({"provider": {"sub": "bound-subject", "token": "discard"}}) if ident == "b" else None
                db.execute(
                    "INSERT INTO user(id,email,role,name,settings,oauth) VALUES(?,?,?,?,?,?)",
                    (ident, email, role, "discard", "discard", oauth),
                )
                db.execute("INSERT INTO auth VALUES(?,?,?,?,?)", (ident, email, self.hash, enabled, "discard"))
            db.execute(
                """INSERT INTO "group"(id,user_id,name,permissions) VALUES('g','a','Operators','{"chat":{"delete":false}}')"""
            )
            db.execute("INSERT INTO group_member(id,group_id,user_id) VALUES('m','g','b')")
            db.execute("""INSERT INTO config(key,value) VALUES('user.permissions','{"chat":{"delete":false}}')""")
            db.execute("INSERT INTO chat VALUES('discard')")
            db.execute("INSERT INTO file VALUES('discard')")

    def test_transfer_and_retry(self):
        self.assertEqual(migration.export_login(self.source, self.bundle)["accounts"], 4)
        self.assertEqual(migration.export_login(self.source, self.bundle)["result"], "ALREADY_EXPORTED")
        with connect(self.bundle) as db:
            self.assertFalse(any("discard" in row for row in db.iterdump()))
        self.assertEqual(migration.import_login(self.bundle, self.target)["result"], "IMPORTED")
        with connect(self.target) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chat").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM file").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT active FROM auth WHERE id='d'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(DISTINCT session_stamp) FROM auth").fetchone()[0], 4)
        self.assertEqual(migration.import_login(self.bundle, self.target)["result"], "ALREADY_IMPORTED")

    def test_transaction_can_resume_after_failure(self):
        migration.export_login(self.source, self.bundle)
        with connect(self.target) as db:
            db.execute("CREATE TRIGGER injected BEFORE INSERT ON auth BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM user").fetchone()[0], 0)
            db.execute("DROP TRIGGER injected")
        self.assertEqual(migration.import_login(self.bundle, self.target)["result"], "IMPORTED")

    def test_duplicate_email_and_subject_rejected_before_export(self):
        for column, value in (("email", "A@example.org"), ("oauth", '{"provider":{"sub":"bound-subject"}}')):
            with self.subTest(field=column):
                with connect(self.source) as db:
                    original = db.execute(f"SELECT {column} FROM user WHERE id='c'").fetchone()[0]
                    db.execute(f"UPDATE user SET {column}=? WHERE id='c'", (value,))
                with self.assertRaises(migration.MigrationError):
                    migration.export_login(self.source, self.bundle)
                self.assertFalse(self.bundle.exists())
                with connect(self.source) as db:
                    db.execute(f"UPDATE user SET {column}=? WHERE id='c'", (original,))

    def test_reject_populated_target_and_conflicting_rerun(self):
        migration.export_login(self.source, self.bundle)
        with connect(self.target) as db:
            db.execute("INSERT INTO chat VALUES('existing')")
        with self.assertRaises(migration.MigrationError):
            migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            db.execute("DELETE FROM chat")
        migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            db.execute("UPDATE auth SET active=1 WHERE id='d'")
        with self.assertRaises(migration.MigrationError):
            migration.import_login(self.bundle, self.target)

    def test_reject_preexisting_session_or_instance_settings(self):
        migration.export_login(self.source, self.bundle)
        with connect(self.target) as db:
            db.execute("CREATE TABLE auth_session(id TEXT)")
            db.execute("INSERT INTO auth_session VALUES('fixture')")
        with self.assertRaises(migration.MigrationError):
            migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            db.execute("DELETE FROM auth_session")
            db.execute("INSERT INTO config(key,value) VALUES('fixture.setting','true')")
        with self.assertRaises(migration.MigrationError):
            migration.import_login(self.bundle, self.target)

    def test_old_environment_defaults_and_new_features(self):
        defaults = '{"workspace":{"tools":true},"chat":{"delete":true}}'
        migration.export_login(self.source, self.bundle, defaults)
        migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            policy = json.loads(db.execute("SELECT value FROM config WHERE key='user.permissions'").fetchone()[0])
            self.assertTrue(policy["workspace"]["tools"])
            self.assertFalse(policy["chat"]["delete"])
            for section, key in migration.NEW_PERMISSIONS:
                self.assertFalse(policy[section][key])

    def test_retired_grant_blocks_export(self):
        with connect(self.source) as db:
            db.execute("""UPDATE "group" SET permissions='{"features":{"direct_tool_servers":true}}'""")
        with self.assertRaises(migration.MigrationError):
            migration.export_login(self.source, self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_numeric_legacy_oauth_id_is_preserved_as_a_subject(self):
        with connect(self.source) as db:
            db.execute("UPDATE user SET oauth=? WHERE id='b'", ('{"github":{"sub":12345}}',))
        migration.export_login(self.source, self.bundle)
        migration.import_login(self.bundle, self.target)
        with connect(self.target) as db:
            (raw,) = db.execute("SELECT oauth FROM user WHERE id='b'").fetchone()
            self.assertEqual(json.loads(raw), {"github": {"sub": "12345"}})

    def test_import_rejects_a_bundle_with_another_link(self):
        migration.export_login(self.source, self.bundle)
        os.link(self.bundle, self.root / "linked.db")
        with self.assertRaises(migration.MigrationError):
            migration.import_login(self.bundle, self.target)


if __name__ == "__main__":
    unittest.main()
