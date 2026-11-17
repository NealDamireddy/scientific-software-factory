import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from factory.catalog_repository import SQLiteCatalogRepository
from factory.context_repository import SQLiteContextRepository
from tests.fixtures.catalog_examples import LAB, Caller, catalog
from tests.test_catalog_contract import CatalogRepositoryContract


class SQLiteCatalogTests(CatalogRepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "shared.sqlite"
        super().setUp()

    def open_repository(self):
        return SQLiteCatalogRepository(self.path)

    def test_migrations_compose_in_either_order(self):
        for context_first in (True, False):
            path = self.path.with_name(f"shared-{context_first}.sqlite")
            if context_first:
                SQLiteContextRepository(path)
            repo = SQLiteCatalogRepository(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], int(context_first))
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                self.assertEqual({t for t in tables if t.startswith("catalog_")},
                                 {"catalog_schema_version", "catalog_revisions", "catalog_approvals"})
            SQLiteContextRepository(path)
            draft = repo.save("catalog", LAB, "draft", {**catalog("unused"), "claims": []},
                              expected_revision=0, principal=Caller())
            self.assertEqual(SQLiteCatalogRepository(path).get("catalog", LAB, "draft", principal=Caller()), draft)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_unknown_version_fails_closed(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE catalog_schema_version SET version=2")
        with self.assertRaisesRegex(ValueError, "version"):
            self.open_repository()

    def test_ddl_collision_rolls_back_migration(self):
        path = self.path.with_name("collision.sqlite")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE catalog_approvals (unrelated TEXT)")
        with self.assertRaises(sqlite3.OperationalError):
            SQLiteCatalogRepository(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall(),
                             [("catalog_approvals",)])

    def test_persisted_revisions_and_receipts_are_immutable(self):
        _, draft = self.new_catalog()
        receipt = self.repo.approve(draft.pin, principal=self.curator)
        with closing(sqlite3.connect(self.path)) as db:
            for table, field in (("catalog_revisions", "payload"), ("catalog_approvals", "approver")):
                for sql in (f"UPDATE {table} SET {field}='overwrite'", f"DELETE FROM {table}",
                            f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"):
                    with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                        db.execute(sql)
            # An explicit hidden rowid could evict a record even if every declared key is new.
            for sql in (
                """INSERT OR REPLACE INTO catalog_revisions
                   (rowid, revision_id, kind, lab_id, record_id, revision, sha256, author, created_at, payload)
                   SELECT rowid, 'new-id', kind, lab_id, 'new-record', 1, sha256, author, created_at, payload
                   FROM catalog_revisions WHERE kind='source'""",
                """INSERT OR REPLACE INTO catalog_approvals (rowid, revision_id, approver, approved_at)
                   SELECT rowid, 'new-id', approver, approved_at FROM catalog_approvals""",
            ):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.OperationalError, "rowid"):
                    db.execute(sql)
        record = self.open_repository().get("catalog", LAB, draft.pin.record_id, principal=self.curator)
        self.assertEqual((record.pin, record.approval), (draft.pin, receipt))
