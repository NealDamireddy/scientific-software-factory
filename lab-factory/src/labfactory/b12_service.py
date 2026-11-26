"""Persist simulated B12 readings and run the exact analysis a reviewer released."""

import json

from .artifacts import RunPlan, RunStep, Setting
from .b12_analysis import CALIBRATION, SAMPLE_READINGS, analyze_readings, validate_readings
from .checks import CheckResult, all_passed, check_artifact
from .context import (
    Command, ContextError, Document, Experiment, Instrument, Lab, Parameter, canonical_digest, canonical_json,
)
from .store import NotFound
from .workorders import WorkOrderError, WorkOrders


EXPERIMENT_ID = "b12-analysis-sim-v1"
_SIM_LAB = Lab("b12-simulation-lab", "B12 simulation lab", (
    Instrument("uvvis-1", "Simulated UV-visible spectrophotometer", "Simulated UV-Vis", "1",
               (Parameter("wavelength", "nm", 400, 700),),
               (Command("read_absorbance", ("wavelength",)),)),
), ())
_CALIBRATION_DOC_ID = "b12-sim-calibration-v1"


def _calibration_document():
    # The canonical payload is part of the experiment revision's digest. Every
    # coefficient and profile identifier used by the evaluator is pinned here.
    text = (
        f"Use three simulated absorbance replicates (AU) at {CALIBRATION['wavelength_nm']} nm. "
        f"The frozen curve is absorbance (AU) = {CALIBRATION['slope_au_per_mg_l']} × "
        f"concentration (mg/L) + {CALIBRATION['intercept_au']}. Each reading must be in "
        f"[{CALIBRATION['min_au']}, {CALIBRATION['max_au']}] AU, inclusive. Average the three "
        "absorbances and invert the curve. Withhold the estimate when any reading is outside range."
    )
    return Document(
        _CALIBRATION_DOC_ID, "standard", "Simulated B12 calibration",
        "Lab Factory simulated reference " + CALIBRATION["id"], text + "\n" + canonical_json(CALIBRATION),
    )


_SIM_EXPERIMENT = Experiment(
    EXPERIMENT_ID, _SIM_LAB.id, "Vitamin B12 concentration from simulated readings",
    "Estimate the simulated B12 concentration at 550 nm using a frozen reference curve.",
    ("uvvis-1",), (_calibration_document(),),
)


def calibration_checks(lab, experiment):
    """Check the analysis profile against the exact context pinned by the order."""
    matches = (
        experiment.id == EXPERIMENT_ID and experiment.lab_id == lab.id == _SIM_LAB.id
        and _calibration_document() in experiment.documents
        and lab.document(_CALIBRATION_DOC_ID) is None
    )
    detail = ("Pinned 550 nm simulated B12 reference curve and triplicate protocol match."
              if matches else "This analysis requires the pinned, unmodified simulated B12 calibration document.")
    setting = Setting("wavelength", CALIBRATION["wavelength_nm"], "nm")
    plan = RunPlan("uvvis-1", (RunStep("read_absorbance", (setting,)),))
    return [CheckResult("frozen B12 calibration", matches, detail), *check_artifact(plan, lab, experiment)]


def require_calibration(lab, experiment):
    for check in calibration_checks(lab, experiment):
        if not check.passed:
            raise WorkOrderError(check.detail)


def _order(store, order_id):
    order = WorkOrders(store).get(order_id)
    if order.kind != "analysis_app" or order.experiment_id != EXPERIMENT_ID:
        raise WorkOrderError(f"{order_id} is not a simulated B12 analysis order")
    return order


def _settings():
    return {"calibration": dict(CALIBRATION), "sample_readings": list(SAMPLE_READINGS)}


def catalog(store):
    with store.read_transaction():
        rows = store.connection.execute(
            "SELECT * FROM work_orders WHERE kind='analysis_app' AND experiment_id=? ORDER BY rowid",
            (EXPERIMENT_ID,),
        )
        return {"orders": [dict(row) for row in rows], **_settings()}


def create_order(store, reviewer):
    with store.transaction():
        try:
            lab, _ = store.get_lab(_SIM_LAB.id)
        except NotFound:
            store.put_lab(_SIM_LAB)
            lab = _SIM_LAB
        try:
            experiment, _ = store.get_experiment(EXPERIMENT_ID)
        except NotFound:
            store.put_experiment(_SIM_EXPERIMENT)
            experiment = _SIM_EXPERIMENT
        order = WorkOrders(store).create(EXPERIMENT_ID, "analysis_app", _SIM_EXPERIMENT.goal, actor=reviewer)
        return {"id": order.id}


def _reading(row):
    receipt = json.loads(row["receipt"]) if row["receipt"] else None
    if receipt is not None:
        receipt["created_at"] = row["ran_at"]
    return {
        "id": row["id"], "readings": json.loads(row["readings"]),
        "created_at": row["created_at"], "actor": row["actor"], "result": receipt,
    }


_READING_QUERY = (
    "SELECT d.id, d.readings, d.created_at, d.actor, r.receipt, r.created_at AS ran_at "
    "FROM b12_readings d LEFT JOIN b12_results r ON r.reading_id=d.id WHERE d.work_order_id=?"
)


def list_readings(store, order_id):
    with store.read_transaction() as db:
        order = _order(store, order_id)
        experiment, _ = store.get_experiment(order.experiment_id, order.experiment_revision)
        doc = next((d for d in experiment.documents if d.id == _CALIBRATION_DOC_ID), None)
        try:
            pinned = json.loads(doc.text.splitlines()[-1]) if doc else None
            if not isinstance(pinned, dict) or not CALIBRATION.keys() <= pinned.keys():
                raise ValueError
        except (ValueError, IndexError):
            raise WorkOrderError("The pinned experiment has no readable B12 calibration.") from None
        rows = db.execute(_READING_QUERY + " ORDER BY d.id DESC", (order_id,))
        return {"readings": [_reading(row) for row in rows], "calibration": pinned,
                "sample_readings": list(SAMPLE_READINGS)}


def _get_reading(db, order_id, reading_id):
    row = db.execute(_READING_QUERY + " AND d.id=?", (order_id, reading_id)).fetchone()
    if row is None:
        raise NotFound(f"No reading set {reading_id} on {order_id}")
    return _reading(row)


def save_readings(store, order_id, reviewer, readings):
    try:
        values = validate_readings(readings)
    except ValueError as exc:
        raise ContextError(str(exc)) from exc
    with store.transaction() as db:
        _order(store, order_id)
        cursor = db.execute(
            "INSERT INTO b12_readings(work_order_id,readings,actor) VALUES (?,?,?)",
            (order_id, canonical_json(values), reviewer),
        )
        return _get_reading(db, order_id, cursor.lastrowid)


def run_readings(store, order_id, reading_id, reviewer, submission):
    if type(submission) is not int or submission < 1:
        raise ContextError("Provide the positive integer submission number to run.")
    with store.transaction() as db:
        order = _order(store, order_id)
        if order.status != "released" or order.released_submission != submission:
            raise WorkOrderError(f"{order_id} must be released for submission {submission} before analysis can run.")
        dataset = _get_reading(db, order_id, reading_id)
        if dataset["result"] is not None:
            return dataset["result"]

        orders = WorkOrders(store)
        release = orders.submission(order_id, submission)
        approval = db.execute(
            "SELECT actor, note FROM events WHERE work_order_id=? AND event='approved' AND submission=? "
            "ORDER BY rowid DESC LIMIT 1", (order_id, submission),
        ).fetchone()
        if not (release and release.passed and all_passed(release.results) and approval
                and approval["note"] == release.artifact_digest == canonical_digest(release.artifact)):
            raise WorkOrderError("The source and approval digest could not be verified.")
        require_calibration(*orders.pinned_context(order_id))
        try:
            result = analyze_readings(release.artifact["source"], dataset["readings"])
        except ValueError as exc:
            raise WorkOrderError(f"The released analysis could not run: {exc}") from exc
        receipt = {
            **result, "work_order_id": order_id, "reading_id": reading_id, "submission": submission,
            "artifact_digest": release.artifact_digest, "readings_digest": canonical_digest(dataset["readings"]),
            "calibration_id": CALIBRATION["id"], "calibration": dict(CALIBRATION),
            "calibration_digest": canonical_digest(CALIBRATION),
            "lab_id": order.lab_id, "lab_revision": order.lab_revision,
            "experiment_id": order.experiment_id, "experiment_revision": order.experiment_revision,
            "actor": reviewer, "approved_by": approval["actor"], "worker": release.worker,
        }
        db.execute("INSERT INTO b12_results(reading_id,work_order_id,submission,receipt) VALUES (?,?,?,?)",
                   (reading_id, order_id, submission, canonical_json(receipt)))
        return _get_reading(db, order_id, reading_id)["result"]
