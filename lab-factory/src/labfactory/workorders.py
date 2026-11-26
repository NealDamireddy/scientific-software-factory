"""Work orders, pinned checks and submission-specific review decisions."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import sqlite3

from .artifacts import KINDS, parse_artifact
from .checks import CheckResult, all_passed, check_artifact
from .context import Experiment, Lab, canonical_digest, canonical_json
from .store import NotFound, Store


class WorkOrderError(RuntimeError):
    """The requested work-order transition is invalid."""


@dataclass(frozen=True)
class WorkOrder:
    id: str
    experiment_id: str
    experiment_revision: int
    lab_id: str
    lab_revision: int
    kind: str
    objective: str
    status: str
    worker: str | None
    released_submission: int | None


@dataclass(frozen=True)
class Submission:
    work_order_id: str
    number: int
    worker: str
    artifact: dict
    artifact_digest: str
    results: tuple[CheckResult, ...]
    passed: bool
    submitted_at: str


def _submission(row: sqlite3.Row) -> Submission:
    return Submission(
        row["work_order_id"], row["number"], row["worker"], json.loads(row["artifact"]),
        row["artifact_digest"], tuple(CheckResult(**r) for r in json.loads(row["results"])),
        bool(row["passed"]), row["submitted_at"],
    )


def _actor(name: str) -> None:
    if not isinstance(name, str) or not name.strip() or not name.isprintable():
        raise WorkOrderError("actor name must be nonempty and printable")


class WorkOrders:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.connection

    def get(self, id: str) -> WorkOrder:
        row = self.db.execute("SELECT * FROM work_orders WHERE id = ?", (id,)).fetchone()
        if row is None:
            raise NotFound(f"unknown work order {id}")
        return WorkOrder(**row)

    def list(self, status: str | None = None) -> list[WorkOrder]:
        if status is None:
            rows = self.db.execute("SELECT * FROM work_orders ORDER BY rowid")
        else:
            rows = self.db.execute("SELECT * FROM work_orders WHERE status = ? ORDER BY rowid", (status,))
        return [WorkOrder(**row) for row in rows]

    def _event(self, id, event, actor, submission=None, note=""):
        self.db.execute(
            "INSERT INTO events (work_order_id, event, actor, submission, note) VALUES (?,?,?,?,?)",
            (id, event, actor, submission, note),
        )

    def create(self, experiment_id: str, kind: str, objective: str) -> WorkOrder:
        if kind not in KINDS:
            raise WorkOrderError(f"unknown work-order kind {kind}")
        if not isinstance(objective, str) or not objective.strip():
            raise WorkOrderError("work order needs an objective")
        with self.store.transaction():
            exp, exp_rev = self.store.get_experiment(experiment_id)
            _, lab_rev = self.store.get_lab(exp.lab_id)
            seq = self.db.execute("SELECT COALESCE(MAX(rowid),0) + 1 FROM work_orders").fetchone()[0]
            id = f"WO-{seq}"
            self.db.execute(
                """INSERT INTO work_orders
                   (id, experiment_id, experiment_revision, lab_id, lab_revision, kind, objective, status)
                   VALUES (?,?,?,?,?,?,?,'open')""",
                (id, exp.id, exp_rev.number, exp.lab_id, lab_rev.number, kind, objective),
            )
            self._event(id, "created", "operator")
            return self.get(id)

    def pinned_context(self, id: str) -> tuple[Lab, Experiment]:
        order = self.get(id)
        lab, _ = self.store.get_lab(order.lab_id, order.lab_revision)
        experiment, _ = self.store.get_experiment(order.experiment_id, order.experiment_revision)
        return lab, experiment

    def _transition(self, id, expected, status, worker, released=None):
        changed = self.db.execute(
            """UPDATE work_orders SET status=?, worker=?, released_submission=?
               WHERE id=? AND status=?""", (status, worker, released, id, expected),
        )
        if changed.rowcount != 1:
            raise WorkOrderError(f"{id} is {self.get(id).status}, expected {expected}")

    def claim(self, id: str, worker: str) -> WorkOrder:
        _actor(worker)
        with self.store.transaction():
            self._transition(id, "open", "in_progress", worker)
            self._event(id, "claimed", worker)
            return self.get(id)

    def submit(self, id: str, worker: str, artifact: dict) -> Submission:
        with self.store.transaction():
            order = self.get(id)
            if order.status != "in_progress":
                raise WorkOrderError(f"{id} is {order.status}, expected in_progress")
            if worker != order.worker:
                raise WorkOrderError(f"{id} belongs to {order.worker}")
            # Validate and persist the same snapshot, including its original JSON types.
            data = deepcopy(artifact)
            parsed = parse_artifact(order.kind, data)
            body = canonical_json(data)
            results = check_artifact(parsed, *self.pinned_context(id))
            passed = all_passed(results)
            number = self.db.execute(
                "SELECT COALESCE(MAX(number),0) + 1 FROM submissions WHERE work_order_id=?", (id,)
            ).fetchone()[0]
            self.db.execute(
                """INSERT INTO submissions (work_order_id, number, worker, artifact, artifact_digest, results, passed)
                   VALUES (?,?,?,?,?,?,?)""",
                (id, number, worker, body, canonical_digest(data), json.dumps([asdict(r) for r in results]), passed),
            )
            self._transition(id, "in_progress", "in_review" if passed else "in_progress", worker)
            self._event(id, "submitted", worker, number, "passed" if passed else "failed")
            row = self.db.execute(
                "SELECT * FROM submissions WHERE work_order_id=? AND number=?", (id, number)
            ).fetchone()
            return _submission(row)

    def submissions(self, id: str) -> list[Submission]:
        return [_submission(row) for row in self.db.execute(
            "SELECT * FROM submissions WHERE work_order_id=? ORDER BY number", (id,)
        )]

    def _reviewed(self, id, number):
        order = self.get(id)
        if order.status != "in_review":
            raise WorkOrderError(f"{id} is {order.status}, expected in_review")
        row = self.db.execute(
            "SELECT * FROM submissions WHERE work_order_id=? ORDER BY number DESC LIMIT 1", (id,)
        ).fetchone()
        if row is None:
            raise WorkOrderError(f"{id} has no submission")
        if type(number) is not int or row["number"] != number:
            raise WorkOrderError(f"submission {number} is not the latest (latest is {row['number']})")
        latest = _submission(row)
        if not latest.passed or not all_passed(latest.results):
            raise WorkOrderError(f"submission {number} has not passed its checks")
        return latest

    def approve(self, id: str, person: str, submission: int) -> WorkOrder:
        _actor(person)
        with self.store.transaction():
            latest = self._reviewed(id, submission)
            self._transition(id, "in_review", "released", latest.worker, submission)
            self._event(id, "approved", person, submission, latest.artifact_digest)
            return self.get(id)

    def reject(self, id: str, person: str, submission: int, reason: str) -> WorkOrder:
        _actor(person)
        if not isinstance(reason, str) or not reason.strip():
            raise WorkOrderError("rejection needs a reason")
        with self.store.transaction():
            self._reviewed(id, submission)
            self._transition(id, "in_review", "open", None)
            self._event(id, "rejected", person, submission, reason)
            return self.get(id)

    def latest_rejection(self, id: str) -> dict | None:
        row = self.db.execute(
            """SELECT e.submission, e.actor, e.note, s.artifact FROM events e
               JOIN submissions s ON (s.work_order_id=e.work_order_id AND s.number=e.submission)
               WHERE e.work_order_id=? AND e.event='rejected' ORDER BY e.rowid DESC LIMIT 1""", (id,)
        ).fetchone()
        if row is None:
            return None
        return {"submission": row["submission"], "by": row["actor"], "reason": row["note"],
                "artifact": json.loads(row["artifact"])}

    def history(self, id: str) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT event, actor, at, submission, note FROM events WHERE work_order_id=? ORDER BY rowid", (id,)
        )]
