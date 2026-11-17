"""SQLite storage for the runtime work-order domain, schema version 2."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .context import digest
from .context_repository import canonical_json
from .runtime_work_order import RevisionConflict, RuntimeRecord, Scope
from .runtime_work_order_domain import RuntimeWorkOrders


_RECORD_SCHEMA = (
    """CREATE TABLE runtime_work_order_records (
        lab_id TEXT NOT NULL, project_id TEXT NOT NULL, work_order_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0), request_key TEXT NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY (lab_id, project_id, work_order_id, version),
        UNIQUE (lab_id, project_id, work_order_id, request_key)
    ) WITHOUT ROWID""",
    # REPLACE deletes the conflicting row without firing its delete trigger on
    # default connections. Reject both unique collisions before SQLite can do so.
    """CREATE TRIGGER runtime_work_order_no_replace BEFORE INSERT ON runtime_work_order_records
       WHEN EXISTS (SELECT 1 FROM runtime_work_order_records
                    WHERE lab_id = NEW.lab_id AND project_id = NEW.project_id
                      AND work_order_id = NEW.work_order_id
                      AND (version = NEW.version OR request_key = NEW.request_key))
       BEGIN SELECT RAISE(ABORT, 'runtime work-order history is immutable'); END""",
    """CREATE TRIGGER runtime_work_order_no_update BEFORE UPDATE ON runtime_work_order_records
       BEGIN SELECT RAISE(ABORT, 'runtime work-order history is immutable'); END""",
    """CREATE TRIGGER runtime_work_order_no_delete BEFORE DELETE ON runtime_work_order_records
       BEGIN SELECT RAISE(ABORT, 'runtime work-order history is immutable'); END""",
)

_SCOPE = "lab_id = ? AND project_id = ? AND work_order_id = ?"


def _identity(scope):
    return scope.lab_id, scope.project_id, scope.work_order_id


class _SQLiteRecordStore:
    def __init__(self, db_path):
        self.path = Path(db_path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS runtime_work_order_schema (
                version INTEGER PRIMARY KEY CHECK (version > 0))""")
            version = db.execute("SELECT MAX(version) FROM runtime_work_order_schema").fetchone()[0]
            if version == 2:
                return
            if version not in (None, 1):
                raise ValueError(f"Unsupported runtime work-order schema version {version}")
            if version == 1:
                # Preserve the original table name used by any shared views. DDL
                # and copies commit together with the domain version marker.
                db.execute("""CREATE TEMP TABLE runtime_work_order_v1 AS
                    SELECT lab_id, project_id, work_order_id, version, request_key, record, sha256
                    FROM runtime_work_order_records""")
                db.execute("DROP TABLE runtime_work_order_records")
            for statement in _RECORD_SCHEMA:
                db.execute(statement)
            if version == 1:
                db.execute("""INSERT INTO runtime_work_order_records
                    (lab_id, project_id, work_order_id, version, request_key, record, sha256)
                    SELECT lab_id, project_id, work_order_id, version, request_key, record, sha256
                    FROM temp.runtime_work_order_v1""")
            db.execute("INSERT INTO runtime_work_order_schema VALUES (2)")

    def read(self, scope: Scope) -> list[RuntimeRecord]:
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(f"""SELECT record, sha256 FROM runtime_work_order_records
                                  WHERE {_SCOPE} ORDER BY version""", _identity(scope))
            records = []
            for encoded, sha256 in rows:
                if digest(encoded.encode()) != sha256:
                    raise ValueError("Stored runtime work-order record digest mismatch")
                records.append(json.loads(encoded))
            return records

    def append(self, scope: Scope, record: RuntimeRecord, *, expected_version: int) -> None:
        encoded = canonical_json(record)
        identity = _identity(scope)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(f"""SELECT COALESCE(MAX(version), 0) FROM runtime_work_order_records
                                     WHERE {_SCOPE}""", identity).fetchone()[0]
            if current != expected_version or record["version"] != current + 1:
                raise RevisionConflict("Work-order history changed during append")
            try:
                db.execute("""INSERT INTO runtime_work_order_records
                              (lab_id, project_id, work_order_id, version, request_key, record, sha256)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""",
                           (*identity, record["version"], record["key"], encoded, digest(encoded.encode())))
            except sqlite3.IntegrityError as exc:
                raise RevisionConflict("Duplicate work-order version or request key") from exc


class SQLiteRuntimeWorkOrderRepository(RuntimeWorkOrders):
    """Use a local persistent file. Each call owns and closes its connections."""
    def __init__(self, db_path: str | Path):
        super().__init__(_SQLiteRecordStore(db_path))
