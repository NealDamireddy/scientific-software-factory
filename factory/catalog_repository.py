"""SQLite implementation of the instrument knowledge repository."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

from .catalog_contract import ApprovalReceipt, CatalogRecord, RevisionPin
from .catalog_domain import CatalogDomainRepository

_MIGRATION_1 = (
    """CREATE TABLE catalog_revisions (
        revision_id TEXT PRIMARY KEY NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('source', 'catalog', 'evidence')),
        lab_id TEXT NOT NULL,
        record_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        sha256 TEXT NOT NULL,
        author TEXT NOT NULL,
        created_at TEXT NOT NULL,
        predecessor_id TEXT REFERENCES catalog_revisions(revision_id),
        payload TEXT NOT NULL,
        UNIQUE (lab_id, kind, record_id, revision),
        CHECK ((revision = 1) = (predecessor_id IS NULL))
    )""",
    """CREATE TABLE catalog_approvals (
        revision_id TEXT PRIMARY KEY NOT NULL REFERENCES catalog_revisions(revision_id),
        approver TEXT NOT NULL,
        approved_at TEXT NOT NULL
    )""",
    # SQLite REPLACE may implicitly delete rows without invoking DELETE triggers.
    """CREATE TRIGGER catalog_revisions_no_replace BEFORE INSERT ON catalog_revisions
       WHEN EXISTS (SELECT 1 FROM catalog_revisions WHERE revision_id=NEW.revision_id
           OR (lab_id=NEW.lab_id AND kind=NEW.kind AND record_id=NEW.record_id AND revision=NEW.revision))
       BEGIN SELECT RAISE(ABORT, 'immutable catalog record'); END""",
    """CREATE TRIGGER catalog_approvals_no_replace BEFORE INSERT ON catalog_approvals
       WHEN EXISTS (SELECT 1 FROM catalog_approvals WHERE revision_id=NEW.revision_id)
       BEGIN SELECT RAISE(ABORT, 'immutable catalog record'); END""",
)

_SELECT = """SELECT r.*, a.approver, a.approved_at
             FROM catalog_revisions r LEFT JOIN catalog_approvals a ON a.revision_id=r.revision_id
             WHERE r.lab_id=? AND r.kind=?"""
_STREAM = _SELECT + " AND r.record_id=?"


def _record(row):
    pin = RevisionPin(row["lab_id"], row["kind"], row["record_id"], row["revision"],
                      row["revision_id"], row["sha256"])
    approval = ApprovalReceipt(pin, row["approver"], row["approved_at"]) if row["approver"] is not None else None
    return CatalogRecord(pin, row["author"], row["created_at"], row["predecessor_id"],
                         json.loads(row["payload"]), approval)


class _SQLiteTransaction:
    def __init__(self, db, kind, lab_id, record_id):
        self.db = db
        self.lab_id = lab_id
        self.params = (lab_id, kind, record_id)

    def read(self, revision):
        if revision is None:
            row = self.db.execute(_STREAM + " ORDER BY r.revision DESC LIMIT 1", self.params).fetchone()
        else:
            row = self.db.execute(_STREAM + " AND r.revision=?", (*self.params, revision)).fetchone()
        return _record(row) if row else None

    def history(self):
        return tuple(_record(row) for row in self.db.execute(_STREAM + " ORDER BY r.revision", self.params))

    def has_source(self, revision_id):
        return self.db.execute("""SELECT 1 FROM catalog_revisions
            WHERE revision_id=? AND lab_id=? AND kind='source'""", (revision_id, self.lab_id)).fetchone() is not None

    def append(self, record, encoded):
        pin = record.pin
        self.db.execute("""INSERT INTO catalog_revisions
            (revision_id, kind, lab_id, record_id, revision, sha256, author, created_at, predecessor_id, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (pin.revision_id, pin.kind, pin.lab_id, pin.record_id, pin.revision, pin.sha256,
                         record.author, record.created_at, record.predecessor_id, encoded))

    def add_receipt(self, receipt):
        self.db.execute("INSERT INTO catalog_approvals (revision_id, approver, approved_at) VALUES (?, ?, ?)",
                        (receipt.pin.revision_id, receipt.approver, receipt.approved_at))


class SQLiteCatalogRepository(CatalogDomainRepository):
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS catalog_schema_version (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1), version INTEGER NOT NULL)""")
            version = db.execute("SELECT version FROM catalog_schema_version WHERE singleton=1").fetchone()
            if version is None:
                for statement in _MIGRATION_1:
                    db.execute(statement)
                for table in ("catalog_revisions", "catalog_approvals"):
                    for operation in ("UPDATE", "DELETE"):
                        db.execute(f"""CREATE TRIGGER {table}_immutable_{operation} BEFORE {operation} ON {table}
                                       BEGIN SELECT RAISE(ABORT, 'immutable catalog record'); END""")
                db.execute("INSERT INTO catalog_schema_version VALUES (1, 1)")
            elif version[0] != 1:
                raise ValueError(f"Unsupported catalog database version: {version[0]}")

    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _read_by_id(self, kind, lab_id, revision_id):
        with closing(self._connect()) as db:
            row = db.execute(_SELECT + " AND r.revision_id=?", (lab_id, kind, revision_id)).fetchone()
        return _record(row) if row else None

    @contextmanager
    def _transaction(self, kind, lab_id, record_id, *, write):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield _SQLiteTransaction(db, kind, lab_id, record_id)
