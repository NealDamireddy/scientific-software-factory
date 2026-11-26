"""SQLite storage for immutable lab and experiment revisions."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import sqlite3

from .context import (
    ContextError, Experiment, Lab, canonical_digest, canonical_json,
    experiment_from_dict, lab_from_dict, to_dict,
)


@dataclass(frozen=True)
class Revision:
    number: int
    digest: str


class NotFound(LookupError):
    """The requested record or revision does not exist."""


_SCHEMA = {
    "records": """
    CREATE TABLE IF NOT EXISTS records (
        kind TEXT NOT NULL,
        id TEXT NOT NULL,
        number INTEGER NOT NULL,
        digest TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (kind, id, number)
    )
    """,
    "work_orders": """
    CREATE TABLE IF NOT EXISTS work_orders (
        id TEXT NOT NULL PRIMARY KEY,
        experiment_id TEXT NOT NULL, experiment_revision INTEGER NOT NULL,
        lab_id TEXT NOT NULL, lab_revision INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('procedure','run_plan')),
        objective TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','in_progress','in_review','released')),
        worker TEXT, released_submission INTEGER,
        FOREIGN KEY (id, released_submission) REFERENCES submissions(work_order_id, number)
    )
    """,
    "submissions": """
    CREATE TABLE IF NOT EXISTS submissions (
        work_order_id TEXT NOT NULL REFERENCES work_orders(id), number INTEGER NOT NULL,
        worker TEXT NOT NULL, artifact TEXT NOT NULL, artifact_digest TEXT NOT NULL,
        results TEXT NOT NULL, passed INTEGER NOT NULL CHECK (passed IN (0,1)),
        submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (work_order_id, number)
    )
    """,
    "events": """
    CREATE TABLE IF NOT EXISTS events (
        work_order_id TEXT NOT NULL REFERENCES work_orders(id), event TEXT NOT NULL,
        actor TEXT NOT NULL, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        submission INTEGER, note TEXT NOT NULL,
        FOREIGN KEY (work_order_id, submission) REFERENCES submissions(work_order_id, number)
    )
    """,
    "events_by_order": "CREATE INDEX IF NOT EXISTS events_by_order ON events(work_order_id)",
}


def _record_data(record: Lab | Experiment) -> dict:
    try:
        return to_dict(record)
    except (TypeError, ValueError) as exc:
        raise ContextError(f"invalid context record: {exc}") from exc


class Store:
    def __init__(self, path: str | os.PathLike):
        self.connection = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        self.connection.row_factory = sqlite3.Row
        try:
            self._initialize_schema()
        except BaseException:
            self.close()
            raise

    def _initialize_schema(self) -> None:
        self.connection.execute("PRAGMA foreign_keys = ON")
        existing = {row["name"] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
        )}
        if not _SCHEMA.keys() <= existing:
            # Concurrent first opens serialize here. Every statement is idempotent.
            with self.transaction() as connection:
                for statement in _SCHEMA.values():
                    connection.execute(statement)

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        with self.connection:
            yield self.connection

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        """Read one committed snapshot without reserving the write lock."""
        self.connection.execute("BEGIN")
        with self.connection:
            yield self.connection

    def _append_revision(self, kind: str, record_id: str, data: dict) -> Revision:
        latest = self.connection.execute(
            "SELECT number, digest FROM records WHERE kind = ? AND id = ? "
            "ORDER BY number DESC LIMIT 1", (kind, record_id),
        ).fetchone()
        fingerprint = canonical_digest(data)
        if latest is not None and latest["digest"] == fingerprint:
            return Revision(latest["number"], fingerprint)
        number = 1 if latest is None else latest["number"] + 1
        self.connection.execute(
            "INSERT INTO records (kind, id, number, digest, body) VALUES (?, ?, ?, ?, ?)",
            (kind, record_id, number, fingerprint, canonical_json(data)),
        )
        return Revision(number, fingerprint)

    def _read_revision(self, kind: str, record_id: str, number: int | None) -> tuple[dict, Revision]:
        sql = "SELECT number, digest, body FROM records WHERE kind = ? AND id = ? "
        if number is None:
            row = self.connection.execute(sql + "ORDER BY number DESC LIMIT 1", (kind, record_id))
        else:
            row = self.connection.execute(sql + "AND number = ?", (kind, record_id, number))
        result = row.fetchone()
        if result is None:
            revision = "" if number is None else f" revision {number}"
            raise NotFound(f"unknown {kind} {record_id}{revision}")
        return json.loads(result["body"]), Revision(result["number"], result["digest"])

    def put_lab(self, lab: Lab) -> Revision:
        validated = lab_from_dict(_record_data(lab))
        with self.transaction():
            return self._append_revision("lab", validated.id, to_dict(validated))

    def get_lab(self, lab_id: str, number: int | None = None) -> tuple[Lab, Revision]:
        data, revision = self._read_revision("lab", lab_id, number)
        return lab_from_dict(data), revision

    def lab_for_experiment(self, exp: Experiment) -> tuple[Lab, Revision]:
        """Load the current lab and validate the experiment's instrument references."""
        try:
            lab, revision = self.get_lab(exp.lab_id)
        except NotFound as exc:
            raise ContextError(str(exc)) from exc
        for instrument_id in exp.instrument_ids:
            if lab.instrument(instrument_id) is None:
                raise ContextError(f"unknown instrument {instrument_id} in lab {lab.id} revision {revision.number}")
        return lab, revision

    def put_experiment(self, exp: Experiment) -> Revision:
        validated = experiment_from_dict(_record_data(exp))
        with self.transaction():
            self.lab_for_experiment(validated)
            return self._append_revision("experiment", validated.id, to_dict(validated))

    def get_experiment(
        self, experiment_id: str, number: int | None = None,
    ) -> tuple[Experiment, Revision]:
        data, revision = self._read_revision("experiment", experiment_id, number)
        return experiment_from_dict(data), revision
