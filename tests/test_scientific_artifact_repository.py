from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from factory import scientific_artifact_repository as storage
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
            self.assertEqual(db.execute("SELECT version FROM sci_artifact_migration ORDER BY version").fetchall(), [(1,), (2,)])
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
            db.execute("INSERT INTO sci_artifact_migration VALUES (99)")
            db.execute("PRAGMA user_version=73")
        with self.assertRaisesRegex(ValueError, "schema version"):
            self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (73,))
            self.assertEqual(db.execute("SELECT version FROM sci_artifact_migration ORDER BY version").fetchall(),
                             [(1,), (2,), (99,)])

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

    def test_v1_upgrade_blocks_replace_by_each_unique_key(self):
        # Build a populated database using precisely the first shipped migration.
        with patch.object(storage, "_MIGRATIONS", storage._MIGRATIONS[:1]):
            old = self.repository(self.principal)
            req = old.save("lab", "project", "requirement", "r", {}, expected_revision=0)
            blueprint = old.save("lab", "project", "blueprint", "b", {}, references=(req.pin,), expected_revision=0)
            spec = old.save("lab", "project", "specification", "s", {}, expected_revision=0)
            receipt = old.decide(spec.pin, "rejected", rationale="Incomplete")
            successor = old.save("lab", "project", "requirement", "r", {"n": 2}, expected_revision=1)
            markers = old.reconciliation(blueprint.pin)

        repo = self.repository(self.principal)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            for table, columns, selection in (
                ("decision", "", "id, specification_id, 'approved', actor_id, decided_at, rationale, limitations"),
                ("revision", "", "id, lab_id, project_id, kind, 'new', revision, sha256, payload, 'fake', predecessor_id"),
                ("revision", "", "NULL, lab_id, project_id, kind, artifact_id, revision, sha256, payload, 'fake', predecessor_id"),
                ("reference", "", "owner_id, position, owner_id"),
                ("reference", "(rowid, owner_id, position, target_id)", "rowid, owner_id, position+10, target_id"),
                ("reconciliation", "", "owner_id, position, owner_id"),
                ("reconciliation", "(rowid, owner_id, position, successor_id)", "rowid, owner_id, position+10, successor_id"),
            ):
                table_name = f"sci_artifact_{table}"
                with self.subTest(table=table, selection=selection):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                        db.execute(f"INSERT OR REPLACE INTO {table_name}{columns} SELECT {selection} FROM {table_name}")

        reopened = self.repository(self.principal)
        self.assertEqual(reopened.decisions(spec.pin), (receipt,))
        self.assertEqual(reopened.get("lab", "project", "specification", "s").state, "rejected")
        self.assertEqual(reopened.history("lab", "project", "requirement", "r"), (req, successor))
        self.assertEqual(reopened.get("lab", "project", "blueprint", "b"), blueprint)
        self.assertEqual(reopened.reconciliation(blueprint.pin), markers)
        # A legitimate second receipt and another revision can still be appended.
        second = repo.decide(spec.pin, "approved", rationale="Reviewed")
        self.assertEqual(reopened.decisions(spec.pin), (receipt, second))
        revision = repo.save("lab", "project", "specification", "s", {}, references=(successor.pin,), expected_revision=1)
        self.assertEqual((revision.predecessor, revision.state), (spec.pin, "draft"))

    def test_upgrade_preserves_appends_from_legacy_negative_rowids(self):
        with patch.object(storage, "_MIGRATIONS", storage._MIGRATIONS[:1]):
            old = self.repository(self.principal)
            spec = old.save("lab", "project", "specification", "s", {}, expected_revision=0)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("""INSERT INTO sci_artifact_decision
                    SELECT -2, id, 'rejected', 'reviewer', '2020-01-01T00:00:00+00:00', 'Incomplete', '[]'
                    FROM sci_artifact_revision""")
            original, = old.decisions(spec.pin)

        repo = self.repository(self.principal)
        later = [repo.decide(spec.pin, "rejected", rationale=f"Review {n}") for n in range(3)]
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(list(db.execute("SELECT id FROM sci_artifact_decision ORDER BY id")),
                             [(-2,), (-1,), (0,), (1,)])
            for record_id in (-2, -1, 0, 1):
                with self.subTest(record_id=record_id), self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute("""INSERT OR REPLACE INTO sci_artifact_decision
                        SELECT id, specification_id, 'approved', actor_id, decided_at, rationale, limitations
                        FROM sci_artifact_decision WHERE id=?""", (record_id,))
        self.assertEqual(repo.decisions(spec.pin), (original, *later))

    def test_upgraded_revision_can_have_predecessor_at_rowid_zero(self):
        with patch.object(storage, "_MIGRATIONS", storage._MIGRATIONS[:1]):
            self.repository(self.principal)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("""INSERT INTO sci_artifact_revision VALUES
                    (-1, 'lab', 'project', 'knowledge', 'k', 1, ?, '{}', 'researcher', NULL)""",
                    (storage.artifact_digest({}, ()),))
        repo = self.repository(self.principal)
        first = repo.get("lab", "project", "knowledge", "k")
        second = repo.save("lab", "project", "knowledge", "k", {}, expected_revision=1)
        third = repo.save("lab", "project", "knowledge", "k", {}, expected_revision=2)
        self.assertEqual(second.predecessor, first.pin)
        self.assertEqual(third.predecessor, second.pin)
        self.assertEqual(repo.history("lab", "project", "knowledge", "k"), (first, second, third))

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
