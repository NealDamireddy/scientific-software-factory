"""Immutable, lab-scoped context revisions for new experiments."""
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Literal, Protocol
from uuid import uuid4

from jsonschema import Draft202012Validator

from factory.context import ROOT, digest, read_json

Kind = Literal["lab", "project"]
_REGISTRY = ROOT / "registry"
_CONTEXT_SCHEMA = read_json(_REGISTRY / "context.schema.json")


def canonical_json(payload: dict) -> str:
    """Canonical UTF-8 input to public profile and context payload digests."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class RevisionConflict(ValueError):
    """An expected revision no longer matches the current entity revision."""


@dataclass(frozen=True)
class ContextRevision:
    revision_id: str
    kind: Kind
    lab_id: str
    project_id: str | None
    revision: int
    sha256: str
    payload: dict
    lab_revision: int | None
    lab_sha256: str | None


class ContextRepository(Protocol):
    def save_lab(self, payload: dict, *, expected_revision: int) -> ContextRevision: ...

    def save_project(self, payload: dict, *, expected_revision: int) -> ContextRevision: ...

    def get(self, kind: Kind, lab_id: str, *, project_id: str | None = None,
            revision: int | None = None) -> ContextRevision: ...


def _validate(validator: Draft202012Validator, payload: dict, label: str) -> None:
    error = next(validator.iter_errors(payload), None)
    if error:
        raise ValueError(f"{label}{error.json_path[1:]}: {error.message}")


def _registered_profiles() -> dict[str, str]:
    schema = Draft202012Validator(read_json(_REGISTRY / "instrument-profile.schema.json"))
    profiles = {}
    for path in sorted(_REGISTRY.glob("*.profile.json")):
        profile = read_json(path)
        _validate(schema, profile, path.name)
        key = profile["profile_id"]
        if key in profiles:
            raise ValueError(f"Duplicate public profile_id: {key}")
        if profile["replicate_limits"]["max"] < profile["replicate_limits"]["min"]:
            raise ValueError(f"{key}: replicate_limits.max must be at least min")
        profiles[key] = digest(canonical_json(profile).encode())
    return profiles


_MIGRATION_1 = (
    """CREATE TABLE context_revisions (
        revision_id TEXT PRIMARY KEY NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('lab', 'project')),
        lab_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision > 0),
        sha256 TEXT NOT NULL,
        payload TEXT NOT NULL,
        lab_revision INTEGER,
        lab_sha256 TEXT,
        UNIQUE (kind, lab_id, project_id, revision),
        CHECK ((kind = 'lab' AND project_id = '' AND lab_revision IS NULL AND lab_sha256 IS NULL)
            OR (kind = 'project' AND project_id != '' AND lab_revision IS NOT NULL AND lab_sha256 IS NOT NULL))
    )""",
    """CREATE TABLE instrument_owners (
        instrument_id TEXT PRIMARY KEY NOT NULL,
        lab_id TEXT NOT NULL
    )""",
    """CREATE TRIGGER immutable_context_update BEFORE UPDATE ON context_revisions
       BEGIN SELECT RAISE(ABORT, 'context revisions are immutable'); END""",
    """CREATE TRIGGER immutable_context_delete BEFORE DELETE ON context_revisions
       BEGIN SELECT RAISE(ABORT, 'context revisions are immutable'); END""",
)


class SQLiteContextRepository:
    """Open a local database by path. Every operation owns and closes its connection."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._profiles = _registered_profiles()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _MIGRATION_1:
                    db.execute(statement)
                db.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise ValueError(f"Unsupported context database version: {version}")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _lookup(db, kind, lab_id, project_id, revision=None):
        query = "SELECT * FROM context_revisions WHERE kind=? AND lab_id=? AND project_id=?"
        params = [kind, lab_id, project_id]
        if revision is not None:
            query += " AND revision=?"
            params.append(revision)
        return db.execute(query + " ORDER BY revision DESC LIMIT 1", params).fetchone()

    def get(self, kind: Kind, lab_id: str, *, project_id: str | None = None,
            revision: int | None = None) -> ContextRevision:
        if kind not in ("lab", "project") or (kind == "project") != (project_id is not None):
            raise ValueError("Supply project_id only when looking up a project")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("revision must be a positive integer")
        with closing(self._connect()) as db:
            row = self._lookup(db, kind, lab_id, project_id or "", revision)
        if row is None:
            raise KeyError(f"No {kind} revision for lab {lab_id!r}, project {project_id!r}, revision {revision}")
        return ContextRevision(**{**dict(row), "project_id": project_id, "payload": json.loads(row["payload"])})

    def save_lab(self, payload: dict, *, expected_revision: int) -> ContextRevision:
        return self._save("lab", payload, expected_revision)

    def save_project(self, payload: dict, *, expected_revision: int) -> ContextRevision:
        return self._save("project", payload, expected_revision)

    def _save(self, kind: Kind, payload: dict, expected_revision: int) -> ContextRevision:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be zero for creation or the current revision for an edit")
        schema = {"$ref": f"#/$defs/{kind}", "$defs": _CONTEXT_SCHEMA["$defs"]}
        _validate(Draft202012Validator(schema), payload, kind)
        encoded = canonical_json(payload)
        lab_id = payload["lab_id"]
        project_id = payload.get("project_id")
        lab_revision = lab_sha256 = None
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._lookup(db, kind, lab_id, project_id or "")
            current = previous["revision"] if previous else 0
            if current != expected_revision:
                raise RevisionConflict(f"{kind} expected_revision={expected_revision}, current={current}; reload and retry")
            if kind == "lab":
                self._claim_instruments(db, lab_id, payload["instruments"])
            else:
                lab = self._lookup(db, "lab", lab_id, "")
                if lab is None:
                    raise ValueError(f"lab_id: save lab {lab_id!r} before creating a project")
                instruments = json.loads(lab["payload"])["instruments"]
                if not any(i["instrument_id"] == payload["instrument_id"] for i in instruments):
                    raise ValueError(f"instrument_id: select an instrument in lab {lab_id!r}")
                lab_revision, lab_sha256 = lab["revision"], lab["sha256"]
            revision_id = str(uuid4())
            sha256 = digest(encoded.encode())
            db.execute("""INSERT INTO context_revisions
                (revision_id, kind, lab_id, project_id, revision, sha256, payload, lab_revision, lab_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                revision_id, kind, lab_id, project_id or "", current + 1, sha256, encoded, lab_revision, lab_sha256,
            ))
        return ContextRevision(revision_id, kind, lab_id, project_id, current + 1, sha256,
                               json.loads(encoded), lab_revision, lab_sha256)

    def _claim_instruments(self, db, lab_id, instruments):
        seen = set()
        for instrument in instruments:
            key = instrument["instrument_id"]
            if key in seen:
                raise ValueError(f"instruments: duplicate instrument_id {key!r}")
            seen.add(key)
            if instrument["lab_id"] != lab_id:
                raise ValueError(f"instruments: select an instrument owned by lab {lab_id!r}")
            if self._profiles.get(instrument["profile_id"]) != instrument["profile_sha256"]:
                raise ValueError(f"instruments[{key}]: use a registered profile_id and its canonical profile_sha256")
            owner = db.execute("SELECT lab_id FROM instrument_owners WHERE instrument_id=?", (key,)).fetchone()
            if owner is None:
                db.execute("INSERT INTO instrument_owners (instrument_id, lab_id) VALUES (?, ?)", (key, lab_id))
            elif owner["lab_id"] != lab_id:
                raise ValueError(f"instruments: {key!r} belongs to another lab; select an instrument owned by {lab_id!r}")
