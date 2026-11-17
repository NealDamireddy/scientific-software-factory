"""Hosted run journal. A claim commits once, before the worker calls acquire.

Only the worker receiving a new claim may dispatch its key. After an ambiguous
response or crash, reconcile performs lookup/poll/cancel using that same key or
job ID. An unconfirmed job keeps its instrument lease, including after cancel.
"""
from contextlib import contextmanager
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Json

from ..experiment_scheduler import seconds
from ..uvvis_contract import InstrumentError, canonical
from .db import Database


class AcquisitionObserver(Protocol):
    def lookup(self, spec_digest: str, key: str) -> str | None: ...
    def poll(self, job_id: str) -> dict: ...
    def cancel(self, job_id: str) -> dict: ...


class AcquisitionBackend(AcquisitionObserver, Protocol):
    def acquire(self, spec_digest: str, key: str) -> str: ...


def _new_run(rid, spec, instrument, at):
    run = dict(run_id=rid, spec_digest=spec, instrument_id=instrument, submitted_at=at,
               dispatch_key="experiment-" + rid, approval=None, recipe="pending", compiled_recipe=None,
               calibration_ready=False, dependency="awaiting readiness check", software="pending",
               acquisition="queued", analysis="pending", job_id=None, release_id=None,
               cancel_requested_at=None, attempts=[], reading_count=None, measurements=None, result=None)
    for lane in ("software", "acquisition", "analysis"):
        for suffix in ("started_at", "finished_at", "elapsed_s", "error"):
            run[f"{lane}_{suffix}"] = None
    return run


class PostgresRunStore(Database):
    def submit(self, key, spec, instrument, at):
        with self.transaction() as db:
            # Committed order on each instrument is also its sequence order.
            db.execute("INSERT INTO instrument_queues VALUES (%s) ON CONFLICT DO NOTHING", (instrument,))
            db.execute("SELECT instrument FROM instrument_queues WHERE instrument=%s FOR UPDATE", (instrument,))
            rid = uuid4().hex
            run = _new_run(rid, spec, instrument, at)
            row = db.execute("""INSERT INTO experiment_runs (run_id,submission_key,instrument,body)
                VALUES (%s,%s,%s,%s) ON CONFLICT (submission_key) DO NOTHING RETURNING run_id""",
                (rid, key, instrument, Json(run))).fetchone()
            if row:
                return rid
            existing = db.execute("SELECT body FROM experiment_runs WHERE submission_key=%s", (key,)).fetchone()["body"]
            if (spec, instrument) != (existing["spec_digest"], existing["instrument_id"]):
                raise ValueError("Submission key already belongs to different inputs")
            return existing["run_id"]

    def lock(self, name, *, blocking=False):
        """RunStore worker lock. Closing the handle or losing the session releases it."""
        db = psycopg.connect(self.dsn, autocommit=True)
        try:
            if blocking:
                db.execute("SELECT pg_advisory_lock(454, hashtext(%s))", (name,))
            elif not db.execute("SELECT pg_try_advisory_lock(454, hashtext(%s))", (name,)).fetchone()[0]:
                db.close()
                return None
            return db
        except BaseException:
            db.close()
            raise

    def active_ids(self):
        with self.transaction() as db:
            return [r["run_id"] for r in db.execute("""SELECT run_id FROM experiment_runs
                WHERE body->>'software'='running' OR body->>'analysis'='running'
                   OR (body->>'acquisition' NOT IN ('cancelled','failed','interrupted')
                       AND body->>'analysis' NOT IN ('completed','failed','cancelled'))
                   OR body->>'acquisition' IN ('running','uncertain','dispatching') ORDER BY seq""")]

    @staticmethod
    def read(db, rid):
        row = db.execute("SELECT body FROM experiment_runs WHERE run_id=%s FOR UPDATE", (rid,)).fetchone()
        if row is None:
            raise KeyError(rid)
        return row["body"]

    def get(self, rid):
        with self.transaction() as db:
            return self.read(db, rid)

    @staticmethod
    def _write(db, run):
        db.execute("UPDATE experiment_runs SET body=%s WHERE run_id=%s",
                   (Json(run, dumps=canonical), run["run_id"]))

    @staticmethod
    def save(db, run):
        original = PostgresRunStore.read(db, run["run_id"])
        fixed = ("run_id", "instrument_id", "dispatch_key", "spec_digest", "submitted_at", "job_id", "dispatch_attempted")
        if any(original.get(key) != run.get(key) for key in fixed):
            raise ValueError("Run identity and dispatch are repository-owned")
        if run["acquisition"] != original["acquisition"] and not (
                run["acquisition"] == "cancelled" and original["acquisition"] == "queued" and run["cancel_requested_at"]):
            raise ValueError("Use the hosted claim and reconciliation operations to change acquisition state")
        if original["cancel_requested_at"] and original["cancel_requested_at"] != run["cancel_requested_at"]:
            raise ValueError("Cancellation intent is already recorded")
        PostgresRunStore._write(db, run)

    @contextmanager
    def edit(self, rid):
        with self.transaction() as db:
            run = self.read(db, rid)
            yield run
            if run["run_id"] != rid:
                raise ValueError("Run identity is immutable")
            self.save(db, run)

    def cancel(self, rid, at):
        with self.edit(rid) as run:
            if run["cancel_requested_at"] or run["analysis"] == "completed":
                return
            run["cancel_requested_at"] = at
            if run["acquisition"] == "queued":
                run["acquisition"] = "cancelled"
            for lane in ("software", "analysis"):
                if run[lane] == "pending":
                    run[lane] = "cancelled"

    def claim(self):
        """Return one ready FIFO head and persist its lease, or None."""
        with self.transaction() as db:
            row = db.execute("""SELECT r.body FROM experiment_runs r
                JOIN instrument_queues q USING (instrument)
                WHERE r.body->>'acquisition' = 'queued'
                  AND r.body->>'cancel_requested_at' IS NULL AND r.body->>'dependency' IS NULL
                  AND r.body->>'recipe' = 'verified' AND (r.body->'calibration_ready')::jsonb = 'true'::jsonb
                  AND r.body->'compiled_recipe'->>'instrument_id' = r.instrument
                  AND r.body->'approval'->>'specification_sha256' = r.body->>'spec_digest'
                  AND NOT EXISTS (SELECT FROM scheduling_leases l WHERE l.instrument=r.instrument)
                  AND NOT EXISTS (SELECT FROM experiment_runs earlier WHERE earlier.instrument=r.instrument
                                  AND earlier.seq < r.seq AND earlier.body->>'acquisition'='queued')
                ORDER BY r.seq LIMIT 1 FOR UPDATE OF q,r SKIP LOCKED""").fetchone()
            if row is None:
                return None
            run = row["body"]
            inserted = db.execute("""INSERT INTO scheduling_leases VALUES (%s,%s)
                ON CONFLICT DO NOTHING RETURNING run_id""", (run["instrument_id"], run["run_id"])).fetchone()
            if inserted is None:
                return None
            run.update(acquisition="dispatching", dispatch_attempted=True)
            self._write(db, run)
            return run

    def dispatch_next(self, backend: AcquisitionBackend):
        """Issue a fresh claim once. Recovery enters through reconcile(), never here."""
        claimed = self.claim()
        if claimed is None:
            return None
        rid = claimed["run_id"]
        # Only this claimant can know that it has not called acquire yet.
        with self.transaction() as db:
            run = self.read(db, rid)
            if run["cancel_requested_at"]:
                run["acquisition"] = "cancelled"
                db.execute("DELETE FROM scheduling_leases WHERE run_id=%s", (rid,))
                self._write(db, run)
                return run
        try:
            jid = backend.acquire(claimed["spec_digest"], claimed["dispatch_key"])
        except Exception as exc:
            with self.transaction() as db:
                run = self.read(db, rid)
                if run["job_id"] or run["acquisition"] not in ("dispatching", "uncertain"):
                    return run  # A concurrent reconciler already observed the job.
                run["acquisition_error"] = f"{type(exc).__name__}: {exc}"[:500]
                # Match the local scheduler's explicit first-POST rejection contract.
                if isinstance(exc, InstrumentError) and exc.status in (409, 422) and exc.field != "Idempotency-Key":
                    busy = exc.status == 409 and exc.field == "instrument_id"
                    run["acquisition"] = "cancelled" if run["cancel_requested_at"] else "queued" if busy else "failed"
                    run["dispatch_attempted"] = False
                    if run["acquisition"] == "failed":
                        run["analysis"] = "blocked"
                    db.execute("DELETE FROM scheduling_leases WHERE run_id=%s", (rid,))
                else:
                    run["acquisition"] = "uncertain"
                self._write(db, run)
                return run
        if isinstance(jid, str) and jid:
            self.record_job(rid, jid)
        return self.reconcile(rid, backend)

    def record_job(self, rid, job_id):
        """Persist the original POST response, or the ID found by keyed lookup."""
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("Missing acquisition identity")
        with self.transaction() as db:
            run = self.read(db, rid)
            if run["job_id"] == job_id:
                return
            if run["acquisition"] not in ("dispatching", "uncertain") or run["job_id"] is not None:
                raise ValueError("Conflicting acquisition identity")
            run["job_id"] = job_id
            self._write(db, run)

    def reconcile(self, rid, backend: AcquisitionObserver):
        """Observe the original remote job. Backend implements lookup, poll and cancel."""
        run = self.get(rid)
        if run["acquisition"] not in ("dispatching", "running", "uncertain"):
            return run
        try:
            jid = run["job_id"] or backend.lookup(run["spec_digest"], run["dispatch_key"])
            self.record_job(rid, jid)
            run = self.get(rid)
            job = backend.cancel(jid) if run["cancel_requested_at"] else backend.poll(jid)
            state = job["status"]
            if job["job_id"] != jid or state not in ("running", "completed", "cancelled", "interrupted"):
                raise ValueError("Unrecognized remote acquisition identity or status")
            start, end = job["started_at"], job["finished_at"]
            if (state == "running") != (end is None):
                raise ValueError("Inconsistent remote termination timestamp")
            elapsed = seconds(end, start) if start and end else None
            reading_count = job["reading_count"]
        except Exception as exc:
            with self.transaction() as db:
                current = self.read(db, rid)
                if current["acquisition"] in ("dispatching", "running", "uncertain"):
                    current.update(acquisition="uncertain", acquisition_error=f"{type(exc).__name__}: {exc}"[:500])
                    self._write(db, current)
                return current
        with self.transaction() as db:
            current = self.read(db, rid)
            if current["acquisition"] in ("dispatching", "running", "uncertain"):
                current.update(acquisition=state, acquisition_started_at=start, acquisition_finished_at=end,
                               acquisition_elapsed_s=elapsed, reading_count=reading_count, acquisition_error=None)
                if state != "running":
                    db.execute("DELETE FROM scheduling_leases WHERE run_id=%s", (rid,))
                    if state != "completed":
                        current.update(analysis="cancelled" if state == "cancelled" else "blocked",
                                       acquisition_error="Acquisition " + state)
                self._write(db, current)
            return current
