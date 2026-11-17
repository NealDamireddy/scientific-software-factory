from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from factory.runtime_work_order import Scope
from factory.runtime_work_order_domain import RuntimeWorkOrders
from factory.runtime_work_order_sqlite import SQLiteRuntimeWorkOrderRepository
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
        with db:
            db.execute("INSERT INTO runtime_work_order_schema VALUES (2)")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            SQLiteRuntimeWorkOrderRepository(self.path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM runtime_work_order_records").fetchone()[0], 1)

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
