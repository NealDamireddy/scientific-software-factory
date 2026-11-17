"""Expected-revision writes serialize on the lab, including its project pins."""
import json
from uuid import uuid4

from jsonschema import Draft202012Validator

from ..context import digest
from ..context_repository import (
    ContextRevision, RevisionConflict, _CONTEXT_SCHEMA, _registered_profiles, _validate, canonical_json,
)
from .db import Database


def _lookup(db, kind, lab_id, project_id, revision=None):
    query = "SELECT * FROM context_revisions WHERE kind=%s AND lab_id=%s AND project_id=%s"
    params = [kind, lab_id, project_id or ""]
    if revision is not None:
        query += " AND revision=%s"
        params.append(revision)
    return db.execute(query + " ORDER BY revision DESC LIMIT 1", params).fetchone()


def _revision(row):
    return ContextRevision(**{**row, "project_id": row["project_id"] or None,
                              "payload": json.loads(row["payload"])})


class PostgresContextRepository(Database):
    def __init__(self, dsn):
        super().__init__(dsn)
        self._profiles = _registered_profiles()

    def get(self, kind, lab_id, *, project_id=None, revision=None):
        if kind not in ("lab", "project") or (kind == "project") != (project_id is not None):
            raise ValueError("Supply project_id only when looking up a project")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("revision must be a positive integer")
        with self.transaction() as db:
            row = _lookup(db, kind, lab_id, project_id, revision)
            if row is None:
                raise KeyError((kind, lab_id, project_id, revision))
            return _revision(row)

    def save_lab(self, payload, *, expected_revision):
        return self._save("lab", payload, expected_revision)

    def save_project(self, payload, *, expected_revision):
        return self._save("project", payload, expected_revision)

    def _save(self, kind, payload, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be zero for creation or the current revision for an edit")
        schema = {"$ref": f"#/$defs/{kind}", "$defs": _CONTEXT_SCHEMA["$defs"]}
        _validate(Draft202012Validator(schema), payload, kind)
        encoded = canonical_json(payload)
        lab_id, project_id = payload["lab_id"], payload.get("project_id")
        with self.transaction() as db:
            db.execute("SELECT pg_advisory_xact_lock(451, hashtext(%s))", (lab_id,))
            previous = _lookup(db, kind, lab_id, project_id)
            current = previous["revision"] if previous else 0
            if current != expected_revision:
                raise RevisionConflict(f"{kind} expected_revision={expected_revision}, current={current}")
            lab_revision = lab_sha256 = None
            if kind == "lab":
                self._claim_instruments(db, lab_id, payload["instruments"])
            else:
                lab = _lookup(db, "lab", lab_id, None)
                if lab is None:
                    raise ValueError(f"lab_id: save lab {lab_id!r} before creating a project")
                instruments = json.loads(lab["payload"])["instruments"]
                if not any(i["instrument_id"] == payload["instrument_id"] for i in instruments):
                    raise ValueError(f"instrument_id: select an instrument in lab {lab_id!r}")
                lab_revision, lab_sha256 = lab["revision"], lab["sha256"]
            row = db.execute("""INSERT INTO context_revisions
                (revision_id, kind, lab_id, project_id, revision, sha256, payload, lab_revision, lab_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (str(uuid4()), kind, lab_id, project_id or "", current + 1, digest(encoded.encode()),
                 encoded, lab_revision, lab_sha256)).fetchone()
            return _revision(row)

    def _claim_instruments(self, db, lab_id, instruments):
        seen = set()
        for item in sorted(instruments, key=lambda i: i["instrument_id"]):
            key = item["instrument_id"]
            if key in seen or item["lab_id"] != lab_id:
                raise ValueError(f"instruments: duplicate or foreign instrument_id {key!r}")
            seen.add(key)
            if self._profiles.get(item["profile_id"]) != item["profile_sha256"]:
                raise ValueError(f"instruments[{key}]: use a registered profile_id and its canonical profile_sha256")
            db.execute("INSERT INTO instrument_owners VALUES (%s,%s) ON CONFLICT DO NOTHING", (key, lab_id))
            owner = db.execute("SELECT lab_id FROM instrument_owners WHERE instrument_id=%s", (key,)).fetchone()
            if owner["lab_id"] != lab_id:
                raise ValueError(f"instruments: {key!r} belongs to another lab")
