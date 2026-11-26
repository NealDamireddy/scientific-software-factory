"""Pin evidence for a simulated HI96800 analysis and execute a reviewed submission."""

import json

from . import references
from .checks import all_passed
from .context import ContextError, Document, Experiment, Instrument, Lab, canonical_digest, canonical_json
from .honey_analysis import SOURCE_IDS, evaluate
from .reference_orders import snapshot_from_findings, source_documents
from .workorders import WorkOrderError, WorkOrders

EXPERIMENT_ID = "honey-moisture-sim-v1"
INSTRUMENT_ID = "hanna-hi96800"
_GOAL = (
    "Determine water in simulated honey, in grams per 100 grams, from duplicate refractive-index "
    "readings at 20 °C. Derive and test the analysis using the pinned publications."
)
_LAB = Lab(
    "honey-refractometry-simulation", "Honey refractometry simulation",
    (Instrument(INSTRUMENT_ID, "Hanna HI96800 refractometer", "HI96800", "Simulated",
                (), (), "Simulated input: duplicate nD20 readings at 20 °C."),), (),
)
INSTRUCTIONS = (
    "Read the original documents linked by the pinned records. Derive the analysis from the "
    "appropriate instrument scale, published method and research evidence. Submit a declarative "
    "analysis with algorithm, table of input/output pairs, citations (id and use), and your own "
    "numerical tests (label, readings, expected). The algorithm is an array of operations. Each "
    "operation takes the preceding output, starting with the input readings. Available primitives: "
    "{\"op\":\"interpolate\",\"table\":\"table\"} for linear interpolation, "
    "{\"op\":\"round\",\"places\":integer} for decimal half-up rounding, and {\"op\":\"mean\"}. "
    "Choose the operations and their order using the sources. The host executes the program and checks "
    "it against independent reference cases. Use the paper to explain applicability and limits. "
    "Address any previous rejection. A reviewer approves a numbered submission before it can run."
)


def current_snapshot():
    result = references.search(INSTRUMENT_ID, "Measure honey moisture")
    findings = [s for s in result["findings"] if s["id"] in SOURCE_IDS]
    if {s["id"] for s in findings} != set(SOURCE_IDS):
        raise WorkOrderError("The reference library is missing a required honey analysis source.")
    return snapshot_from_findings(result, findings)


def _experiment(snapshot):
    stamp = Document(
        "honey-reference-edition", "note", "Simulated honey study and source edition",
        "Lab Factory honey simulation, version 1",
        f"Reference brief SHA-256: {canonical_digest(snapshot)}. Use two simulated refractive-index "
        "readings at 20 °C. The calculation and its numerical tests are supplied by the submitting agent.",
    )
    return Experiment(EXPERIMENT_ID, _LAB.id, "Honey moisture by refractometry", _GOAL,
                      (INSTRUMENT_ID,), (*source_documents(snapshot), stamp))


def require_context(lab, experiment, snapshot):
    if not snapshot or lab != _LAB or experiment != _experiment(snapshot):
        raise WorkOrderError("This analysis requires its original pinned honey references and simulated instrument.")


def is_honey_order(order):
    return order.kind == "analysis_app" and order.experiment_id == EXPERIMENT_ID


def require_order(order):
    if not is_honey_order(order):
        raise WorkOrderError(f"{order.id} is not a simulated honey analysis order")


def catalog(store):
    with store.read_transaction() as db:
        rows = db.execute("SELECT * FROM work_orders WHERE kind='analysis_app' AND experiment_id=? ORDER BY rowid",
                          (EXPERIMENT_ID,))
        return {"orders": [dict(row) for row in rows]}


def create_order(store, reviewer):
    snapshot = current_snapshot()
    with store.transaction():
        store.put_lab(_LAB)
        store.put_experiment(_experiment(snapshot))
        order = WorkOrders(store).create(EXPERIMENT_ID, "analysis_app", _GOAL, actor=reviewer)
        return {"id": order.id}


def _receipt(row):
    return {**json.loads(row["receipt"]), "id": row["id"], "created_at": row["created_at"]}


def list_runs(db, order_id):
    rows = db.execute("SELECT id, created_at, receipt FROM honey_runs WHERE work_order_id=? ORDER BY id DESC",
                      (order_id,))
    return [_receipt(row) for row in rows]


def run(store, order_id, reviewer, readings, submission=None):
    if submission is not None and (type(submission) is not int or submission < 1):
        raise ContextError("Provide the positive integer submission number to run.")
    with store.transaction() as db:
        orders = WorkOrders(store)
        order = orders.get(order_id)
        require_order(order)
        if order.status != "released" or not order.released_submission:
            raise WorkOrderError("A reviewer must release this honey analysis before it can run.")
        if submission is not None and submission != order.released_submission:
            raise WorkOrderError("The requested submission does not match the released honey analysis.")
        submission = order.released_submission
        release = orders.submission(order_id, submission)
        approval = db.execute(
            "SELECT actor, note FROM events WHERE work_order_id=? AND event='approved' AND submission=? "
            "ORDER BY rowid DESC LIMIT 1", (order_id, submission),
        ).fetchone()
        if not (release and release.passed and all_passed(release.results) and approval
                and approval["note"] == release.artifact_digest == canonical_digest(release.artifact)):
            raise WorkOrderError("The approved honey submission and its artifact digest could not be verified.")
        brief = store.reference_brief(order_id)
        require_context(*orders.pinned_context(order_id), brief)
        try:
            estimate = evaluate(release.artifact, readings)
        except ValueError as exc:
            raise ContextError(str(exc)) from exc
        readings_digest = canonical_digest(readings)
        receipt = {
            **estimate, "work_order_id": order_id, "submission": submission, "readings": readings,
            "readings_digest": readings_digest, "artifact_digest": release.artifact_digest,
            "approved_by": approval["actor"], "worker": release.worker, "actor": reviewer,
            "lab_id": order.lab_id, "lab_revision": order.lab_revision,
            "experiment_id": order.experiment_id, "experiment_revision": order.experiment_revision,
            "instrument_id": INSTRUMENT_ID, "catalog_digest": brief["catalog_digest"],
            "reference_brief_digest": canonical_digest(brief),
            "source_digests": {s["id"]: s["digest"] for s in brief["findings"]},
            "unit": "g water per 100 g honey", "temperature_c": 20, "simulated": True,
        }
        key = (order_id, submission, reviewer, readings_digest)
        db.execute(
            "INSERT INTO honey_runs(work_order_id, submission, actor, readings_digest, receipt) VALUES (?,?,?,?,?) "
            "ON CONFLICT(work_order_id, submission, actor, readings_digest) DO NOTHING",
            (*key, canonical_json(receipt)),
        )
        row = db.execute(
            "SELECT id, created_at, receipt FROM honey_runs WHERE work_order_id=? AND submission=? "
            "AND actor=? AND readings_digest=?", key,
        ).fetchone()
        return _receipt(row)
