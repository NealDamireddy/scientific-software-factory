from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from factory.context_repository import RevisionConflict, SQLiteContextRepository
from factory.scientific_artifact_repository import SQLiteScientificArtifactRepository
from tests.fixtures.scientific_artifact_contract import FixturePrincipal, check_repository


class ScientificArtifactTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.sqlite"
        self.principal = FixturePrincipal()

    def repository(self, principal):
        return SQLiteScientificArtifactRepository(self.path, principal)

    def test_adapter_contract(self):
        check_repository(self, self.repository)

    def test_shared_database_migrates_in_either_order(self):
        SQLiteContextRepository(self.path)
        self.repository(self.principal)
        self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT version FROM sci_artifact_migration").fetchall(), [(1,)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM context_revisions").fetchone(), (0,))
        self.path = self.path.with_name("science-first.sqlite")
        self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))
        SQLiteContextRepository(self.path)
        self.repository(self.principal)

    def test_unknown_domain_version_fails_without_overwriting_data(self):
        self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE sci_artifact_migration SET version=2")
            db.execute("PRAGMA user_version=73")
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (73,))
            self.assertEqual(db.execute("SELECT version FROM sci_artifact_migration").fetchall(), [(2,)])

    def test_record_and_receipt_are_append_only(self):
        repo = self.repository(self.principal)
        spec = repo.save("lab", "project", "specification", "spec", {"actor_id": "fake", "state": "approved"},
                         expected_revision=0)
        self.assertEqual((spec.author_id, spec.state), ("researcher", "draft"))
        receipt = repo.decide(spec.pin, "rejected", rationale="Review incomplete")
        spec.payload.clear()
        with closing(sqlite3.connect(self.path)) as db:
            for sql in ("DELETE FROM sci_artifact_revision", "DELETE FROM sci_artifact_decision",
                        "UPDATE sci_artifact_revision SET payload='{}'",
                        "UPDATE sci_artifact_decision SET decision='approved'"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute(sql)
        self.assertEqual(repo.decisions(spec.pin), (receipt,))
        self.assertEqual(repo.get("lab", "project", "specification", "spec").payload["actor_id"], "fake")

    def test_simultaneous_writes_preserve_one_successor(self):
        repo = self.repository(self.principal)
        original = repo.save("lab", "project", "specification", "s", {}, expected_revision=0)
        barrier = threading.Barrier(2)

        def edit(actor):
            worker = self.repository(FixturePrincipal(actor))
            barrier.wait(timeout=5)
            try:
                return worker.save("lab", "project", "specification", "s", {"from": actor}, expected_revision=1)
            except RevisionConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, ("author-a", "author-b")))
        self.assertEqual(results.count(None), 1)
        winner, = filter(None, results)
        self.assertEqual(winner.predecessor, original.pin)
        self.assertEqual(repo.history("lab", "project", "specification", "s"), (original, winner))

    def test_denial_precedes_database_lookup(self):
        class NoConnection(SQLiteScientificArtifactRepository):
            def _connect(self):
                raise AssertionError("Unauthorized database access")

        repo = object.__new__(NoConnection)
        repo.principal = FixturePrincipal(actions=())
        with self.assertRaises(PermissionError):
            repo.get("lab", "project", "knowledge", "missing")
        with self.assertRaises(PermissionError):
            repo.save("lab", "project", "requirement", "missing", None, expected_revision=-1)
