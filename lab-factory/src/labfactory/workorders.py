"""Work orders, pinned checks and submission-specific review decisions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json
import sqlite3

from . import library
from .artifacts import ArtifactError, KINDS, parse_artifact
from .checks import CheckResult, all_passed, check_artifact
from .citations import CitationIndex
from .context import ContextError, Document, Experiment, Lab, canonical_digest, canonical_json
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
class PinnedCitation:
    origin: str
    record_id: str
    revision: int
    document: Document


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

    def create(self, experiment_id: str, kind: str, objective: str, *, actor: str = "operator",
               tabular_upload: bool = False) -> WorkOrder:
        _actor(actor)
        if kind not in KINDS:
            raise WorkOrderError(f"unknown work-order kind {kind}")
        if not isinstance(objective, str) or not objective.strip():
            raise WorkOrderError("work order needs an objective")
        with self.store.transaction():
            exp, exp_rev = self.store.get_experiment(experiment_id)
            if kind == "run_plan" and not exp.instrument_ids:
                raise WorkOrderError("Assign an instrument to the experiment before creating a run plan.")
            try:
                lab, lab_rev = self.store.lab_for_experiment(exp)
            except ContextError as exc:
                raise WorkOrderError(f"cannot pin context for experiment {exp.id}: {exc}") from exc
            snapshot = None
            if kind == "analysis_app":
                from .b12_service import require_calibration
                from . import honey_service

                from . import tabular_service

                if exp.id.startswith(tabular_service.PREFIX):
                    if not tabular_upload:
                        raise WorkOrderError("Create this analysis from a protocol and readings upload.")
                elif exp.id == honey_service.EXPERIMENT_ID:
                    snapshot = honey_service.current_snapshot()
                    honey_service.require_context(lab, exp, snapshot)
                else:
                    require_calibration(lab, exp)
            seq = self.db.execute("SELECT COALESCE(MAX(rowid),0) + 1 FROM work_orders").fetchone()[0]
            id = f"WO-{seq}"
            self.db.execute(
                """INSERT INTO work_orders
                   (id, experiment_id, experiment_revision, lab_id, lab_revision, kind, objective, status)
                   VALUES (?,?,?,?,?,?,?,'open')""",
                (id, exp.id, exp_rev.number, exp.lab_id, lab_rev.number, kind, objective),
            )
            self._event(id, "created", actor)
            if snapshot is not None:
                self.db.execute("INSERT INTO reference_briefs(work_order_id,snapshot) VALUES (?,?)",
                                (id, canonical_json(snapshot)))
            return self.get(id)

    def pinned_context(self, id: str) -> tuple[Lab, Experiment]:
        return self._context_for(self.get(id))

    def citation(self, id: str, document_id: str) -> PinnedCitation:
        order = self.get(id)
        lab, experiment = self._context_for(order)
        origin, document = CitationIndex(lab, experiment).resolve(document_id)
        if document.id.startswith(library.PREFIX) and document in library.documents(self.store, order.id):
            pin = next(p for p in library.pinned(self.store, order.id) if p["document_id"] == document.id)
            return PinnedCitation("library", pin["source_id"], pin["revision"], document)
        if origin == "lab":
            return PinnedCitation(origin, lab.id, order.lab_revision, document)
        return PinnedCitation(origin, experiment.id, order.experiment_revision, document)

    def _context_for(self, order: WorkOrder) -> tuple[Lab, Experiment]:
        lab, _ = self.store.get_lab(order.lab_id, order.lab_revision)
        experiment, _ = self.store.get_experiment(order.experiment_id, order.experiment_revision)
        used = {doc.id for doc in (*lab.documents, *experiment.documents)}
        linked = tuple(doc for doc in library.documents(self.store, order.id) if doc.id not in used)
        if linked:
            experiment = replace(experiment, documents=(*linked, *experiment.documents))
        return lab, experiment

    def _check(self, order: WorkOrder, data: dict) -> list[CheckResult]:
        from . import honey_service

        lab, exp = self._context_for(order)
        if honey_service.is_honey_order(order):
            from .honey_analysis import check

            honey_service.require_context(lab, exp, self.store.reference_brief(order.id))
            return check(data)
        if order.kind == "procedure":
            from . import procedure_drafts
            draft = procedure_drafts.info(self.store, order.id)
            if draft and draft["next_order"]:
                raise WorkOrderError(f"Continue drafting on {draft['next_order']}")
            if draft and isinstance(data, dict) and set(data) == {"needs_input"}:
                return procedure_drafts.question_check(data)
            procedure = parse_artifact(order.kind, data)
            results = check_artifact(procedure, lab, exp)
            if draft or any(step.evidence for step in procedure.steps):
                results.extend(procedure_drafts.evidence_checks(procedure, lab, exp, required=bool(draft)))
            if draft:
                from . import decision_evidence
                from .paper_review import saved_checks
                results.extend(saved_checks(self.store, order.id, data, procedure, lab, exp))
                results.extend(decision_evidence.saved_checks(self.store, order.id, data))
            return results
        return check_artifact(parse_artifact(order.kind, data), lab, exp)

    def _transition(self, id, expected, status, worker, released=None):
        changed = self.db.execute(
            """UPDATE work_orders SET status=?, worker=?, released_submission=?
               WHERE id=? AND status=?""", (status, worker, released, id, expected),
        )
        if changed.rowcount != 1:
            raise WorkOrderError(f"{id} is {self.get(id).status}, expected {expected}")

    def claim(self, id: str, worker: str, *, untagged_artifact: dict | None = None) -> WorkOrder:
        _actor(worker)
        with self.store.transaction():
            if untagged_artifact is not None:
                self._require_untagged_claim(id, worker)
                self._require_new_untagged_digest(id, worker, canonical_digest(untagged_artifact))
            self._transition(id, "open", "in_progress", worker)
            self._event(id, "claimed", worker)
            return self.get(id)

    def active_claim_id(self, order: WorkOrder) -> int | None:
        """Read the claim number from the same transaction as the order snapshot."""
        if order.status != "in_progress":
            return None
        # The per-order ordinal survives database reopen and SQLite rowid changes.
        count = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE work_order_id=? AND event='claimed'", (order.id,)
        ).fetchone()[0]
        return count or None

    def requeue(self, id: str, person: str, claim_id: int, reason: str) -> WorkOrder:
        _actor(person)
        if type(claim_id) is not int or claim_id < 1:
            raise WorkOrderError("provide a positive claim ID")
        if not isinstance(reason, str) or not reason.strip():
            raise WorkOrderError("requeue needs a reason")
        with self.store.transaction():
            order = self.get(id)
            if order.status != "in_progress":
                raise WorkOrderError(f"{id} is {order.status}, expected in_progress")
            if self.active_claim_id(order) != claim_id:
                raise WorkOrderError(f"claim {claim_id} is no longer active for {id}")
            self._transition(id, "in_progress", "open", None)
            self._event(id, "requeued", person, note=f"Claim {claim_id} held by {order.worker}: {reason}")
            return self.get(id)

    def _was_displaced(self, id: str, worker: str) -> bool:
        # The requeue actor is the reviewer. Its preceding claim identifies the worker,
        # including for recovery events recorded before submissions carried a claim ID.
        claimed_by = None
        for event, actor in self.db.execute(
            """SELECT event, actor FROM events WHERE work_order_id=?
               AND event IN ('claimed', 'requeued') ORDER BY rowid""", (id,)
        ):
            if event == "claimed":
                claimed_by = actor
            elif claimed_by == worker:
                return True
        return False

    def _require_untagged_claim(self, id: str, worker: str) -> None:
        if self._was_displaced(id, worker):
            raise WorkOrderError(f"claim_id is required after recovery of an earlier claim by {worker} on {id}")

    def _require_new_untagged_digest(self, id: str, worker: str, fingerprint: str) -> None:
        rejected = self.db.execute(
            """SELECT 1 FROM events e
               JOIN submissions s ON s.work_order_id=e.work_order_id AND s.number=e.submission
               WHERE e.work_order_id=? AND e.event='rejected'
                 AND s.worker=? AND s.artifact_digest=? LIMIT 1""",
            (id, worker, fingerprint),
        ).fetchone()
        if rejected is not None:
            raise WorkOrderError(f"claim_id is required to resubmit an artifact previously rejected for {worker} on {id}")

    def submit(self, id: str, worker: str, artifact: dict, claim_id: int | None = None) -> Submission:
        with self.store.transaction():
            order = self.get(id)
            if order.status != "in_progress":
                raise WorkOrderError(f"{id} is {order.status}, expected in_progress")
            if worker != order.worker:
                raise WorkOrderError(f"{id} belongs to {order.worker}")
            if claim_id is not None:
                if type(claim_id) is not int or claim_id < 1:
                    raise WorkOrderError("provide a positive claim ID")
                if self.active_claim_id(order) != claim_id:
                    raise WorkOrderError(f"claim {claim_id} is no longer active for {id}")
            else:
                self._require_untagged_claim(id, worker)
            # Validate and persist the same snapshot, including its original JSON types.
            data = deepcopy(artifact)
            body = canonical_json(data)
            fingerprint = canonical_digest(data)
            if claim_id is None:
                self._require_new_untagged_digest(id, worker, fingerprint)
            from . import tabular_service

            report = None
            if tabular_service.is_order(order):
                results, report = tabular_service.submission_checks(self.store, order, data)
            else:
                results = self._check(order, data)
            passed = all_passed(results)
            number = self.db.execute(
                "SELECT COALESCE(MAX(number),0) + 1 FROM submissions WHERE work_order_id=?", (id,)
            ).fetchone()[0]
            self.db.execute(
                """INSERT INTO submissions (work_order_id, number, worker, artifact, artifact_digest, results, passed)
                   VALUES (?,?,?,?,?,?,?)""",
                (id, number, worker, body, fingerprint, json.dumps([asdict(r) for r in results]), passed),
            )
            if report is not None:
                tabular_service.record_report(self.db, id, number, report)
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

    def submission(self, id: str, number: int | None = None) -> Submission | None:
        """Read one immutable submission, or the latest one for this order."""
        if number is None:
            row = self.db.execute(
                "SELECT * FROM submissions WHERE work_order_id=? ORDER BY number DESC LIMIT 1", (id,)
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT * FROM submissions WHERE work_order_id=? AND number=?", (id, number)
            ).fetchone()
            if row is None:
                raise NotFound(f"{id} has no submission {number}")
        return _submission(row) if row is not None else None

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
        return order, latest

    def approve(self, id: str, person: str, submission: int) -> WorkOrder:
        _actor(person)
        with self.store.transaction():
            order, latest = self._reviewed(id, submission)
            if latest.artifact_digest != canonical_digest(latest.artifact):
                raise WorkOrderError(f"submission {submission} does not match its stored artifact digest")
            # A submission can outlive the version of the checker that first reviewed it.
            try:
                from . import tabular_service

                if tabular_service.is_order(order):
                    results, _ = tabular_service.submission_checks(self.store, order, latest.artifact, approval=submission)
                else:
                    results = self._check(order, latest.artifact)
            except ArtifactError as exc:
                raise WorkOrderError(f"submission {submission} is invalid under current checks: {exc}") from exc
            if not all_passed(results):
                failures = ", ".join(f"{r.name}: {r.detail}" for r in results if not r.passed)
                raise WorkOrderError(f"submission {submission} fails current checks: {failures}")
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
