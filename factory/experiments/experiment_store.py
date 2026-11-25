"""Local run journal. The application never opens the instrument's database."""
from contextlib import closing, contextmanager
import fcntl
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from factory.instruments.uvvis_contract import canonical


class RunStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.locks = self.path.parent / (self.path.name + ".scheduler-locks")
        self.locks.mkdir(mode=0o700, exist_ok=True)
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiment_runs (
                seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, submission_key TEXT NOT NULL UNIQUE,
                instrument TEXT NOT NULL, body TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS scheduling_leases (
                instrument TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE)""")

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def lock(self, name, *, blocking=False):
        # OS closes the descriptor on process death. Never unlink live lock files.
        handle = (self.locks / name).open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            handle.close()
            return None
        return handle

    def submit(self, key, spec, instrument, at):
        with self.transaction() as db:
            row = db.execute("SELECT body FROM experiment_runs WHERE submission_key=?", (key,)).fetchone()
            if row:
                run = json.loads(row[0])
                if (spec, instrument) != (run["spec_digest"], run["instrument_id"]):
                    raise ValueError("Submission key already belongs to different inputs")
                return run["run_id"]
            rid = uuid4().hex
            run = dict(run_id=rid, spec_digest=spec, instrument_id=instrument, submitted_at=at,
                       dispatch_key="experiment-" + rid, approval=None, recipe="pending", compiled_recipe=None,
                       calibration_ready=False, dependency="awaiting readiness check", software="pending",
                       acquisition="queued", analysis="pending", job_id=None, release_id=None,
                       cancel_requested_at=None, attempts=[], reading_count=None, measurements=None, result=None)
            for lane in ("software", "acquisition", "analysis"):
                for suffix in ("started_at", "finished_at", "elapsed_s", "error"):
                    run[f"{lane}_{suffix}"] = None
            db.execute("INSERT INTO experiment_runs(run_id,submission_key,instrument,body) VALUES (?,?,?,?)",
                       (rid, key, instrument, canonical(run)))
            return rid

    def active_ids(self):
        with closing(sqlite3.connect(self.path)) as db:
            return [r[0] for r in db.execute("""SELECT run_id FROM experiment_runs
                WHERE json_extract(body,'$.software')='running' OR json_extract(body,'$.analysis')='running'
                   OR (json_extract(body,'$.acquisition') NOT IN ('cancelled','failed','interrupted')
                       AND json_extract(body,'$.analysis') NOT IN ('completed','failed','cancelled'))
                   OR json_extract(body,'$.acquisition') IN ('running','uncertain','dispatching')
                ORDER BY seq""")]

    @staticmethod
    def read(db, rid):
        row = db.execute("SELECT body FROM experiment_runs WHERE run_id=?", (rid,)).fetchone()
        if not row:
            raise KeyError(rid)
        return json.loads(row[0])

    def get(self, rid):
        with closing(sqlite3.connect(self.path)) as db:
            return self.read(db, rid)

    @staticmethod
    def save(db, run):
        db.execute("UPDATE experiment_runs SET body=? WHERE run_id=?", (canonical(run), run["run_id"]))

    @contextmanager
    def edit(self, rid):
        with self.transaction() as db:
            run = self.read(db, rid)
            yield run
            self.save(db, run)
