from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from factory.context import digest
from factory.lab_context.context_repository import canonical_json
from factory.software.runtime_work_order import Scope
from factory.software.runtime_work_order_domain import RuntimeWorkOrders
from factory.software.runtime_work_order_sqlite import SQLiteRuntimeWorkOrderRepository
from tests.test_runtime_work_order_contract import FixturePrincipal, run_runtime_work_order_contract, task_fixture


class SQLiteRuntimeWorkOrderTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "shared.sqlite"

    def test_shared_contract(self):
        run_runtime_work_order_contract(lambda: SQLiteRuntimeWorkOrderRepository(self.path))

    def test_composable_migration_and_immutable_records(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        with db:
            db.execute("PRAGMA user_version = 17")
            db.execute("CREATE TABLE unrelated (value TEXT)")
            db.execute("INSERT INTO unrelated VALUES ('retained')")
        repo = SQLiteRuntimeWorkOrderRepository(self.path)
        actor = FixturePrincipal("author", ["revise"])
        repo.apply(actor, Scope("lab", "project", "order"), "revise", task_fixture(), expected_version=0, key="a")
        SQLiteRuntimeWorkOrderRepository(self.path)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 17)
        self.assertEqual(db.execute("SELECT value FROM unrelated").fetchone()[0], "retained")
        for sql in ("UPDATE runtime_work_order_records SET record = '{}'", "DELETE FROM runtime_work_order_records"):
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"), db:
                db.execute(sql)
        original = db.execute("SELECT * FROM runtime_work_order_records").fetchone()
        for version, key in ((1, "changed-key"), (2, "a")):
            replacement = (*original[:3], version, key, *original[5:])
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"), db:
                db.execute("INSERT OR REPLACE INTO runtime_work_order_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                           replacement)
        self.assertEqual(db.execute("SELECT * FROM runtime_work_order_records").fetchall(), [original])
        with db:
            db.execute("INSERT INTO runtime_work_order_schema VALUES (3)")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            SQLiteRuntimeWorkOrderRepository(self.path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_work_order_records").fetchone()[0], 1)

    def test_hidden_rowid_replacement_cannot_evict_history(self):
        repo = SQLiteRuntimeWorkOrderRepository(self.path)
        actor = FixturePrincipal("author", ["revise", "history"])
        scope = Scope("lab", "project", "order")
        original = repo.apply(actor, scope, "revise", task_fixture(), expected_version=0, key="original")
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        # The first row in the original schema had rowid 1. Use different values
        # for both scoped uniqueness constraints so their guards cannot match.
        for alias in ("rowid", "_rowid_", "oid"):
            with self.subTest(alias=alias), self.assertRaisesRegex(sqlite3.OperationalError, "no column"), db:
                db.execute(f"""INSERT OR REPLACE INTO runtime_work_order_records
                    ({alias}, lab_id, project_id, work_order_id, version, request_key, record, sha256)
                    VALUES (1, 'other-lab', 'other-project', 'other-order', 2, 'other-key', '{{}}', 'other')""")
        self.assertEqual(SQLiteRuntimeWorkOrderRepository(self.path).history(actor, scope), [original])

    def test_upgrade_preserves_v1_history_and_closes_rowid_path(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        with db:
            db.execute("PRAGMA user_version = 17")
            db.execute("CREATE TABLE runtime_work_order_schema (version INTEGER PRIMARY KEY CHECK (version > 0))")
            db.execute("INSERT INTO runtime_work_order_schema VALUES (1)")
            db.execute("""CREATE TABLE runtime_work_order_records (
                lab_id TEXT NOT NULL, project_id TEXT NOT NULL, work_order_id TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0), request_key TEXT NOT NULL,
                record TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY (lab_id, project_id, work_order_id, version),
                UNIQUE (lab_id, project_id, work_order_id, request_key))""")
            db.execute("CREATE VIEW order_versions AS SELECT version FROM runtime_work_order_records")
        # Use the current domain contract to construct genuine records, then seed
        # their exact serialized bytes into the legacy table.
        source = SQLiteRuntimeWorkOrderRepository(self.path.with_name("source.sqlite"))
        scope = Scope("lab", "project", "order")
        actor = FixturePrincipal("human", ["history", "revise"])
        expected = []
        for i in range(2):
            record = source.apply(actor, scope, "revise", task_fixture(), expected_version=i, key=str(i))
            expected.append(record)
            encoded = canonical_json(record)
            with db:
                db.execute("INSERT INTO runtime_work_order_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (scope.lab_id, scope.project_id, scope.work_order_id, i + 1, str(i),
                            encoded, digest(encoded.encode())))
        original_rows = db.execute("SELECT * FROM runtime_work_order_records ORDER BY version").fetchall()
        rowid = db.execute("SELECT rowid FROM runtime_work_order_records WHERE version=1").fetchone()[0]

        with db:
            db.execute("""CREATE TRIGGER runtime_test_fail_upgrade BEFORE INSERT ON runtime_work_order_schema
                          BEGIN SELECT RAISE(ABORT, 'injected upgrade failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected upgrade failure"):
            SQLiteRuntimeWorkOrderRepository(self.path)
        self.assertEqual(db.execute("SELECT MAX(version) FROM runtime_work_order_schema").fetchone(), (1,))
        self.assertEqual(db.execute("SELECT rowid FROM runtime_work_order_records WHERE version=1").fetchone(), (rowid,))
        self.assertEqual(db.execute("SELECT * FROM runtime_work_order_records ORDER BY version").fetchall(),
                         original_rows)
        with db:
            db.execute("DROP TRIGGER runtime_test_fail_upgrade")

        upgraded = SQLiteRuntimeWorkOrderRepository(self.path)
        self.assertEqual(upgraded.history(actor, scope), expected)
        self.assertEqual(db.execute("SELECT * FROM runtime_work_order_records ORDER BY version").fetchall(),
                         original_rows)
        with self.assertRaisesRegex(sqlite3.OperationalError, "no column"), db:
            db.execute("""INSERT OR REPLACE INTO runtime_work_order_records
                (rowid, lab_id, project_id, work_order_id, version, request_key, record, sha256)
                VALUES (?, 'other', 'other', 'other', 3, 'changed', '{}', 'other')""", (rowid,))
        self.assertEqual(db.execute("SELECT MAX(version) FROM runtime_work_order_schema").fetchone(), (2,))
        self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (17,))
        self.assertEqual(db.execute("SELECT * FROM order_versions ORDER BY version").fetchall(), [(1,), (2,)])
        self.assertEqual(upgraded.apply(actor, scope, "revise", task_fixture(), expected_version=0, key="0"),
                         expected[0])
        expected.append(upgraded.apply(actor, scope, "revise", task_fixture(), expected_version=2, key="2"))
        self.assertEqual(SQLiteRuntimeWorkOrderRepository(self.path).history(actor, scope), expected)

    def test_failed_migration_rolls_back_domain_ddl(self):
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        with db:
            db.execute("CREATE TABLE runtime_work_order_records (legacy TEXT)")
        with self.assertRaisesRegex(sqlite3.OperationalError, "already exists"):
            SQLiteRuntimeWorkOrderRepository(self.path)
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        self.assertEqual(tables, [("runtime_work_order_records",)])

    def test_authorize_before_any_lookup(self):
        store = Mock()
        repo = RuntimeWorkOrders(store)
        actor = FixturePrincipal("agent", ["resolve"])
        scope = Scope("lab", "project", "unknown")
        with self.assertRaises(PermissionError):
            repo.history(actor, scope)
        with self.assertRaises(PermissionError):
            repo.apply(actor, scope, "resolve", {}, expected_version=0, key="replay")
        with self.assertRaises(PermissionError):
            repo.apply(actor, scope, "claim", {}, expected_version=0, key="replay")
        self.assertEqual(store.mock_calls, [])
