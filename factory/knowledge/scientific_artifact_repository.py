"""SQLite persistence for project-scoped scientific artifacts."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from factory.lab_context.context_repository import RevisionConflict, canonical_json
from factory.knowledge.scientific_artifact import (
    DECIDE, READ, WRITE, ArtifactPin, ArtifactRevision, DecisionReceipt, Principal,
    ReconciliationMarker, artifact_digest,
)

_KINDS = ("knowledge", "requirement", "blueprint", "specification")
_KEY = "lab_id=? AND project_id=? AND kind=? AND artifact_id=?"
_MIGRATION = (
    """CREATE TABLE sci_artifact_revision (
        id INTEGER PRIMARY KEY, lab_id TEXT NOT NULL, project_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('knowledge','requirement','blueprint','specification')),
        artifact_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision > 0),
        sha256 TEXT NOT NULL, payload TEXT NOT NULL, author_id TEXT NOT NULL,
        predecessor_id INTEGER REFERENCES sci_artifact_revision,
        UNIQUE(lab_id, project_id, kind, artifact_id, revision))""",
    """CREATE TABLE sci_artifact_reference (
        owner_id INTEGER NOT NULL REFERENCES sci_artifact_revision,
        position INTEGER NOT NULL, target_id INTEGER NOT NULL REFERENCES sci_artifact_revision,
        PRIMARY KEY(owner_id, position))""",
    "CREATE INDEX sci_artifact_dependents ON sci_artifact_reference(target_id)",
    """CREATE TABLE sci_artifact_decision (
        id INTEGER PRIMARY KEY, specification_id INTEGER NOT NULL REFERENCES sci_artifact_revision,
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')), actor_id TEXT NOT NULL,
        decided_at TEXT NOT NULL, rationale TEXT NOT NULL, limitations TEXT NOT NULL)""",
    "CREATE INDEX sci_artifact_receipts ON sci_artifact_decision(specification_id, id)",
    """CREATE TABLE sci_artifact_reconciliation (
        owner_id INTEGER NOT NULL, position INTEGER NOT NULL,
        successor_id INTEGER NOT NULL REFERENCES sci_artifact_revision,
        PRIMARY KEY(owner_id, position),
        FOREIGN KEY(owner_id, position) REFERENCES sci_artifact_reference(owner_id, position))""",
)


def _create_records(db):
    for sql in _MIGRATION:
        db.execute(sql)
    for table in ("revision", "reference", "decision", "reconciliation"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER sci_artifact_{table}_{operation}
                BEFORE {operation} ON sci_artifact_{table}
                BEGIN SELECT RAISE(ABORT, 'immutable scientific record'); END""")


def _guard_replacements(db):
    # REPLACE can delete a conflicting row without running DELETE triggers.
    # Every table has a rowid, including the two with composite primary keys.
    # With an implicit id the BEFORE trigger can see a negative placeholder.
    # Track actual nonpositive ids separately, including v1 rows, so such a
    # placeholder cannot be mistaken for an explicit replacement. In a normal
    # repository all generated ids are positive and this table stays empty.
    db.execute("""CREATE TABLE sci_artifact_nonpositive_ids (
        table_name TEXT NOT NULL, record_id INTEGER NOT NULL CHECK(record_id <= 0),
        PRIMARY KEY(table_name, record_id)) WITHOUT ROWID""")
    for operation in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER sci_artifact_nonpositive_ids_{operation}
            BEFORE {operation} ON sci_artifact_nonpositive_ids
            BEGIN SELECT RAISE(ABORT, 'immutable scientific record'); END""")

    for table, additional_key in (
        ("revision", ("lab_id", "project_id", "kind", "artifact_id", "revision")),
        ("reference", ("owner_id", "position")),
        ("decision", ()),
        ("reconciliation", ("owner_id", "position")),
    ):
        name = f"sci_artifact_{table}"
        collision = "rowid=NEW.rowid AND NEW.rowid > 0"
        if additional_key:
            collision += " OR (" + " AND ".join(f"{col}=NEW.{col}" for col in additional_key) + ")"
        db.execute(f"""CREATE TRIGGER {name}_no_replace BEFORE INSERT ON {name}
            WHEN EXISTS (SELECT 1 FROM {name} WHERE {collision})
            BEGIN SELECT RAISE(ABORT, 'immutable scientific record'); END""")
        db.execute(f"""INSERT INTO sci_artifact_nonpositive_ids
            SELECT ?, rowid FROM {name} WHERE rowid <= 0""", (table,))
        db.execute(f"""CREATE TRIGGER {name}_nonpositive_rowid AFTER INSERT ON {name}
            WHEN NEW.rowid <= 0 BEGIN
                SELECT RAISE(ABORT, 'immutable scientific record')
                    FROM sci_artifact_nonpositive_ids WHERE table_name='{table}' AND record_id=NEW.rowid;
                INSERT INTO sci_artifact_nonpositive_ids VALUES ('{table}', NEW.rowid);
            END""")


_MIGRATIONS = (_create_records, _guard_replacements)


def _migrate(db):
    db.execute("BEGIN IMMEDIATE")
    db.execute("CREATE TABLE IF NOT EXISTS sci_artifact_migration (version INTEGER PRIMARY KEY)")
    versions = [row[0] for row in db.execute("SELECT version FROM sci_artifact_migration ORDER BY version")]
    expected = list(range(1, len(_MIGRATIONS) + 1))
    if versions != expected[:len(versions)]:
        raise ValueError("Unsupported scientific artifact schema version")
    for version in expected[len(versions):]:
        _MIGRATIONS[version - 1](db)
        db.execute("INSERT INTO sci_artifact_migration VALUES (?)", (version,))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _key(lab_id, project_id, kind, artifact_id):
    if not all(_text(s) for s in (lab_id, project_id, artifact_id)) or kind not in _KINDS:
        raise ValueError("Supply lab_id, project_id, artifact kind and artifact_id")
    return lab_id, project_id, kind, artifact_id


def _pin(row):
    return ArtifactPin(**{field: row[field] for field in ArtifactPin.__dataclass_fields__})


def _lookup(db, key, revision=None):
    query = "SELECT * FROM sci_artifact_revision WHERE " + _KEY
    if revision is None:
        return db.execute(query + " ORDER BY revision DESC LIMIT 1", key).fetchone()
    if type(revision) is not int or revision <= 0:
        raise ValueError("revision must be a positive integer")
    return db.execute(query + " AND revision=?", (*key, revision)).fetchone()


def _resolve(db, pin):
    key = _key(pin.lab_id, pin.project_id, pin.kind, pin.artifact_id)
    if pin.revision is None:
        raise ValueError("An exact revision is required")
    row = _lookup(db, key, pin.revision)
    if row is None:
        raise KeyError("Unknown scientific artifact revision")
    if pin.sha256 != row["sha256"]:
        raise ValueError("Scientific artifact digest mismatch")
    return row


def _by_id(db, row_id):
    return db.execute("SELECT * FROM sci_artifact_revision WHERE id=?", (row_id,)).fetchone()


def _revision(db, row):
    targets = db.execute("""SELECT r.* FROM sci_artifact_reference e
        JOIN sci_artifact_revision r ON r.id=e.target_id
        WHERE e.owner_id=? ORDER BY e.position""", (row["id"],))
    references = tuple(_pin(target) for target in targets)
    payload = json.loads(row["payload"])
    if artifact_digest(payload, references) != row["sha256"]:
        raise ValueError("Stored scientific artifact digest mismatch")
    predecessor = _pin(_by_id(db, row["predecessor_id"])) if row["predecessor_id"] is not None else None
    decision = db.execute("""SELECT decision FROM sci_artifact_decision
        WHERE specification_id=? ORDER BY id DESC LIMIT 1""", (row["id"],)).fetchone()
    return ArtifactRevision(_pin(row), predecessor, row["author_id"], payload, references,
                            decision["decision"] if decision else "draft")


def _reconcile(db, kind, owner_id, predecessor_id):
    # Both insertion orders matter: a requirement can change after a blueprint
    # pins it, or a newly drafted blueprint can explicitly cite an older revision.
    if kind == "requirement" and predecessor_id is not None:
        db.execute("""INSERT INTO sci_artifact_reconciliation
            SELECT e.owner_id, e.position, ? FROM sci_artifact_reference e
            JOIN sci_artifact_revision b ON b.id=e.owner_id
            WHERE e.target_id=? AND b.kind='blueprint'""", (owner_id, predecessor_id))
    if kind == "blueprint":
        db.execute("""INSERT INTO sci_artifact_reconciliation
            SELECT e.owner_id, e.position, successor.id FROM sci_artifact_reference e
            JOIN sci_artifact_revision successor ON successor.predecessor_id=e.target_id
            WHERE e.owner_id=? AND successor.kind='requirement'""", (owner_id,))


class SQLScientificArtifactRepository:
    """Shared domain operations; a trusted adapter supplies transaction(write=...).

    Yield a DB executor with execute(sql, params) returning a cursor supporting
    fetchone() and iteration over name-keyed rows, and executemany(sql, params).
    SQL uses positional ? parameters and INSERT ... RETURNING id. Reads need a
    consistent snapshot. Serialize writes before the first SELECT (including
    decisions versus edits), commit only on normal exit, roll back on error.

    Use the four data tables/columns and foreign keys in _MIGRATION, with
    adapter-native identities, immutability enforcement and migration tracking.
    """
    def __init__(self, principal: Principal):
        self.principal = principal

    def transaction(self, *, write: bool):
        raise NotImplementedError

    def _authorize(self, lab_id, project_id, action):
        self.principal.require(lab_id=lab_id, project_id=project_id, action=action)
        if not _text(self.principal.actor_id):
            raise PermissionError("Authenticated actor required")

    def save(self, lab_id, project_id, kind, artifact_id, payload, *, expected_revision, references=()):
        self._authorize(lab_id, project_id, WRITE)
        key = _key(lab_id, project_id, kind, artifact_id)
        if not isinstance(references, (tuple, list)):
            raise ValueError("Supply a sequence of artifact pins")
        references = tuple(references)
        if references:
            self._authorize(lab_id, project_id, READ)
        for ref in references:
            if not isinstance(ref, ArtifactPin):
                raise ValueError("Supply exact artifact pins")
            if (ref.lab_id, ref.project_id) != (lab_id, project_id):
                raise PermissionError("Scientific references must belong to this project")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be zero or a positive integer")
        if not isinstance(payload, dict):
            raise ValueError("Scientific payload must be a JSON object")
        try:
            encoded = canonical_json(payload)
        except TypeError as exc:
            raise ValueError("Scientific payload must contain JSON fields") from exc
        snapshot = json.loads(encoded)
        if snapshot != payload:
            raise ValueError("Scientific payload must contain JSON fields")
        sha = artifact_digest(snapshot, references)
        with self.transaction(write=True) as db:
            previous = _lookup(db, key)
            current = previous["revision"] if previous else 0
            if current != expected_revision:
                raise RevisionConflict(f"expected_revision={expected_revision}, current={current}")
            target_ids = [_resolve(db, ref)["id"] for ref in references]
            predecessor_id = previous["id"] if previous else None
            cursor = db.execute("""INSERT INTO sci_artifact_revision
                (lab_id,project_id,kind,artifact_id,revision,sha256,payload,author_id,predecessor_id)
                VALUES (?,?,?,?,?,?,?,?,?) RETURNING id""",
                (*key, current + 1, sha, encoded, self.principal.actor_id, predecessor_id))
            owner_id = cursor.fetchone()["id"]
            db.executemany("INSERT INTO sci_artifact_reference VALUES (?,?,?)",
                           ((owner_id, pos, target) for pos, target in enumerate(target_ids)))
            _reconcile(db, kind, owner_id, predecessor_id)
            return _revision(db, _by_id(db, owner_id))

    def get(self, lab_id, project_id, kind, artifact_id, *, revision=None):
        self._authorize(lab_id, project_id, READ)
        key = _key(lab_id, project_id, kind, artifact_id)
        with self.transaction(write=False) as db:
            row = _lookup(db, key, revision)
            if row is None:
                raise KeyError("Unknown scientific artifact revision")
            return _revision(db, row)

    def history(self, lab_id, project_id, kind, artifact_id):
        self._authorize(lab_id, project_id, READ)
        key = _key(lab_id, project_id, kind, artifact_id)
        with self.transaction(write=False) as db:
            rows = db.execute("SELECT * FROM sci_artifact_revision WHERE " + _KEY + " ORDER BY revision", key)
            records = tuple(_revision(db, row) for row in rows)
            if not records:
                raise KeyError("Unknown scientific artifact")
            return records

    def decide(self, specification, decision, *, rationale, limitations=()):
        self._authorize(specification.lab_id, specification.project_id, DECIDE)
        if self.principal.is_human is not True:
            raise PermissionError("Human scientific decision required")
        if specification.kind != "specification" or decision not in ("approved", "rejected"):
            raise ValueError("Supply a scientific specification pin and decision")
        if not _text(rationale) or not isinstance(limitations, (tuple, list)):
            raise ValueError("Supply a rationale and a sequence of limitations")
        limitations = tuple(limitations)
        if not all(_text(item) for item in limitations):
            raise ValueError("Limitations must contain text")
        with self.transaction(write=True) as db:
            row = _resolve(db, specification)
            latest = _lookup(db, (specification.lab_id, specification.project_id,
                                  specification.kind, specification.artifact_id))
            if row["id"] != latest["id"]:
                raise RevisionConflict("Decision targets an obsolete specification revision")
            decided_at = datetime.now(timezone.utc).isoformat()
            actor = self.principal.actor_id
            db.execute("""INSERT INTO sci_artifact_decision
                (specification_id,decision,actor_id,decided_at,rationale,limitations) VALUES (?,?,?,?,?,?)""",
                (row["id"], decision, actor, decided_at, rationale, json.dumps(limitations)))
            return DecisionReceipt(specification, decision, actor, decided_at, rationale, limitations)

    def decisions(self, specification):
        self._authorize(specification.lab_id, specification.project_id, READ)
        if specification.kind != "specification":
            raise ValueError("Supply a scientific specification pin")
        with self.transaction(write=False) as db:
            row = _resolve(db, specification)
            receipts = db.execute("""SELECT * FROM sci_artifact_decision
                WHERE specification_id=? ORDER BY id""", (row["id"],))
            return tuple(DecisionReceipt(specification, r["decision"], r["actor_id"], r["decided_at"],
                                         r["rationale"], tuple(json.loads(r["limitations"]))) for r in receipts)

    def reconciliation(self, blueprint):
        self._authorize(blueprint.lab_id, blueprint.project_id, READ)
        if blueprint.kind != "blueprint":
            raise ValueError("Supply a scientific blueprint pin")
        with self.transaction(write=False) as db:
            row = _resolve(db, blueprint)
            markers = db.execute("""SELECT e.target_id, m.successor_id FROM sci_artifact_reconciliation m
                JOIN sci_artifact_reference e USING (owner_id,position)
                WHERE m.owner_id=? ORDER BY m.position""", (row["id"],))
            return tuple(ReconciliationMarker(blueprint, _pin(_by_id(db, m["target_id"])),
                                              _pin(_by_id(db, m["successor_id"]))) for m in markers)


class SQLiteScientificArtifactRepository(SQLScientificArtifactRepository):
    def __init__(self, db_path: str | Path, principal: Principal):
        self.db_path = Path(db_path)
        super().__init__(principal)
        with closing(self._connect()) as db, db:
            _migrate(db)

    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def transaction(self, *, write):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
