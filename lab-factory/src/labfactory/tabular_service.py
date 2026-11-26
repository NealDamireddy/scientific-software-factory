"""Versioned protocol + readings intake, sealed control verification, and release receipts."""

from dataclasses import asdict
import csv
import io
import json
import math
from uuid import UUID, uuid4

from . import references, tabular_files
from .checks import CheckResult, all_passed
from .context import ContextError, Document, Experiment, Lab, canonical_digest, canonical_json
from .store import NotFound
from .workorders import WorkOrderError, WorkOrders


LAB = Lab("tabular-workspace", "Analysis workspace", (), ())
PREFIX = "tabular-"
MAX_ROWS = 128


def is_order(order):
    return order.kind == "analysis_app" and order.experiment_id.startswith(PREFIX)


def _text(value, field, limit):
    try:
        valid = (isinstance(value, str) and value.strip() and len(value.encode("utf-8")) <= limit
                 and "\x00" not in value)
    except UnicodeError:
        valid = False
    if not valid:
        raise ContextError(f"Provide {field} (up to {limit} UTF-8 bytes).")
    return value


def _filename(value, suffixes):
    value = _text(value, "an upload filename", 200)
    if (not value.lower().endswith(suffixes) or not value.isprintable()
            or any(c in value for c in ("/", "\\"))):
        raise ContextError("Use a plain filename ending in " + " or ".join(suffixes) + ".")
    return value


def _number(value, field):
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError
        return number
    except (OverflowError, TypeError, ValueError):
        raise ContextError(f"Provide a finite number for {field}.") from None


def _control(signal, factor, expected, tolerance):
    result = dict(signal=_number(signal, "control signal"), factor=_number(factor, "control factor"),
                  expected=_number(expected, "control reference value"),
                  tolerance=_number(tolerance, "absolute control tolerance"))
    if result["factor"] <= 0 or result["tolerance"] < 0:
        raise ContextError("The factor must be positive and the absolute tolerance must be nonnegative.")
    return result


def _columns(mapping):
    required = {"id", "role", "signal"}
    if not isinstance(mapping, dict) or not required <= set(mapping) <= required | {"factor", "known"}:
        raise ContextError("Map the sample ID, role and signal columns; optionally map known values and factors.")
    result = {k: _text(mapping[k], f"the {k} column", 160) for k in required}
    for k in ("factor", "known"):
        result[k] = _text(mapping[k], f"the {k} column", 160) if mapping.get(k) else ""
    names = [v for v in result.values() if v]
    if len(set(names)) != len(names):
        raise ContextError("Each mapped column must have a different name.")
    return result


def _batch(request, mapping, range_gate):
    name = _filename(request.get("csv_name"), (".csv",))
    raw = _text(request.get("csv"), "CSV readings", 128 * 1024)
    reader = csv.reader(io.StringIO(raw.lstrip("\ufeff"), newline=""), strict=True)
    standards, controls, unknowns, ids = [], [], [], set()
    try:
        headers = next(reader, [])
        if not (1 <= len(headers) <= 50) or len(set(headers)) != len(headers) or any(not v.strip() for v in headers):
            raise ContextError("Use one CSV header row with unique, nonempty column names (up to 50).")
        if not {v for v in mapping.values() if v} <= set(headers):
            raise ContextError("Every mapped column must exist in this CSV.")
        for n, values in enumerate(reader, 2):
            if not values or all(not v.strip() for v in values):
                continue
            if len(values) != len(headers) or len(ids) >= MAX_ROWS:
                raise ContextError(f"Check CSV row {n}; the file must be rectangular and have at most {MAX_ROWS} samples.")
            row = dict(zip(headers, values))
            name_id = _text(row[mapping["id"]].strip(), f"a sample ID in row {n}", 120)
            if name_id in ids:
                raise ContextError(f"Duplicate sample ID in CSV row {n}.")
            ids.add(name_id)
            role = row[mapping["role"]].strip().lower()
            signal = _number(row[mapping["signal"]], f"signal in row {n}")
            factor = _number(row[mapping["factor"]], f"factor in row {n}") if mapping["factor"] else 1.0
            if factor <= 0:
                raise ContextError(f"Supply a positive factor in row {n}.")
            known = row[mapping["known"]].strip() if mapping["known"] else ""
            if role == "standard":
                if factor != 1:
                    raise ContextError(f"Provide standards on their measured basis with factor 1 in row {n}.")
                standards.append([signal, _number(known, f"standard reference value in row {n}")])
            elif role in ("unknown", "control"):
                if known:
                    raise ContextError("Only standards may have known values in the CSV. Enter the control target separately.")
                target = unknowns if role == "unknown" else controls
                target.append({"id": name_id, "signal": signal, "factor": factor})
            else:
                raise ContextError(f"Use standard, control or unknown as the role in CSV row {n}.")
    except csv.Error as exc:
        raise ContextError(f"Invalid CSV: {exc}") from None
    if len(controls) != 1 or not unknowns:
        raise ContextError("Supply exactly one control and at least one unknown.")
    if range_gate and len({row[0] for row in standards}) < 2:
        raise ContextError("Range-gated analysis requires at least two distinct standard signals.")
    c = controls[0]
    control = _control(c["signal"], c["factor"], request.get("control_expected"), request.get("control_tolerance"))
    return {"csv_name": name, "csv_digest": tabular_files.digest(raw), "standards": standards, "unknowns": unknowns}, control


def _intake(store, order_id):
    row = store.connection.execute("SELECT profile,batch FROM tabular_intakes WHERE work_order_id=?", (order_id,)).fetchone()
    if not row:
        raise NotFound(f"No general analysis upload for {order_id}")
    profile, batch = json.loads(row["profile"]), json.loads(row["batch"])
    stamp = profile.pop("intake_digest", None)
    if stamp != canonical_digest({"profile": profile, "batch": batch}):
        raise WorkOrderError("The stored analysis mapping, calibration or readings differ from the pinned intake.")
    orders = WorkOrders(store)
    order = orders.get(order_id)
    lab, exp = orders.pinned_context(order_id)
    if (not is_order(order) or lab != LAB or exp != _experiment(order.experiment_id, profile, batch)
            or order.objective != profile["objective"]):
        raise WorkOrderError("The analysis intake does not match its pinned experiment revision.")
    return profile, batch


def _latest_control(db, order_id):
    row = db.execute("SELECT edition,value FROM tabular_controls WHERE work_order_id=? ORDER BY edition DESC LIMIT 1",
                     (order_id,)).fetchone()
    value = json.loads(row["value"])
    stamp = value.pop("digest", None)
    if stamp != canonical_digest(value):
        raise WorkOrderError("The sealed control differs from its pinned digest.")
    return row["edition"], value


def _used(db, order_id, edition):
    return db.execute("SELECT 1 FROM tabular_reports WHERE work_order_id=? AND edition=?",
                      (order_id, edition)).fetchone() is not None


def _new_control(db, order_id, edition, control, reviewer):
    db.execute("INSERT INTO tabular_controls(work_order_id,edition,value,actor) VALUES (?,?,?,?)",
               (order_id, edition, canonical_json({**control, "digest": canonical_digest(control)}), reviewer))


def _public_spec(profile, batch):
    fields = ("objective", "unit", "mapping", "range_gate", "protocol_digest", "references")
    return {**{k: profile[k] for k in fields}, "standards": batch["standards"]}


def _experiment(exp_id, profile, batch):
    document = Document("analysis-specification", "note", "Analysis input specification",
                        "Reviewer upload", canonical_json(_public_spec(profile, batch)))
    return Experiment(exp_id, LAB.id, profile["objective"], profile["objective"], (), (document,))


def create_order(store, reviewer, request):
    required = {"objective", "protocol_name", "protocol", "csv_name", "csv", "unit", "mapping",
                "control_expected", "control_tolerance"}
    if not required <= set(request) <= required | {"range_gate", "reference_ids", "request_id"}:
        raise ContextError("Supply protocol and CSV uploads, an objective, column mapping, result unit and control settings.")
    key = request.get("request_id")
    if key is not None:
        try:
            key = str(UUID(str(key)))
        except ValueError:
            raise ContextError("Use a UUID as the analysis request ID.") from None
    objective = _text(request["objective"], "an objective", 1000)
    unit = _text(request["unit"], "a result unit and basis", 100)
    protocol = _text(request["protocol"], "a text or Markdown protocol", 32 * 1024)
    protocol_name = _filename(request["protocol_name"], (".txt", ".md", ".markdown"))
    mapping = _columns(request["mapping"])
    range_gate = request.get("range_gate", True)
    if type(range_gate) is not bool:
        raise ContextError("Range gate must be true or false.")
    batch, control = _batch(request, mapping, range_gate)
    selected = request.get("reference_ids", [])
    if (not isinstance(selected, list) or len(selected) > 10 or any(not isinstance(v, str) for v in selected)
            or len(set(selected)) != len(selected)):
        raise ContextError("Select up to ten different library sources.")
    sources = [references.source(identifier) for identifier in selected]
    profile = dict(objective=objective, unit=unit, mapping=mapping, range_gate=range_gate,
                   protocol_name=protocol_name, protocol_digest=tabular_files.digest(protocol), references=sources)
    exp_id = PREFIX + uuid4().hex
    # The pinned public context contains no private bytes, filenames, row identifiers,
    # controls or unknown readings. Pin only the values the author can use.
    exp = _experiment(exp_id, profile, batch)
    profile["intake_digest"] = canonical_digest({"profile": profile, "batch": batch})
    with store.transaction() as db:
        if key is not None:
            fingerprint = canonical_digest({k: v for k, v in request.items() if k != "request_id"})
            prior = db.execute("SELECT work_order_id,digest FROM tabular_requests WHERE actor=? AND request_id=?",
                               (reviewer, key)).fetchone()
            if prior is not None:
                if fingerprint != prior["digest"]:
                    raise WorkOrderError("This request ID was already used for a different upload.")
                return {"id": prior["work_order_id"]}
        tabular_files.save(db, protocol)
        tabular_files.save(db, request["csv"])
        store.put_lab(LAB)
        store.put_experiment(exp, allow_unassigned=True)
        order = WorkOrders(store).create(exp_id, "analysis_app", objective, actor=reviewer, tabular_upload=True)
        db.execute("INSERT INTO tabular_intakes(work_order_id,profile,batch) VALUES (?,?,?)",
                   (order.id, canonical_json(profile), canonical_json(batch)))
        _new_control(db, order.id, 1, control, reviewer)
        if key is not None:
            db.execute("INSERT INTO tabular_requests(actor,request_id,digest,work_order_id) VALUES (?,?,?,?)",
                       (reviewer, key, fingerprint, order.id))
        return {"id": order.id}


def public_context(store, order):
    profile, batch = _intake(store, order.id)
    public = _public_spec(profile, batch)
    latest = WorkOrders(store).submission(order.id)
    edition, _ = _latest_control(store.connection, order.id)
    return {**public, "protocol": tabular_files.load(store.connection, profile["protocol_digest"]),
            "awaiting_fresh_control": order.status in ("open", "in_progress") and _used(store.connection, order.id, edition),
            "last_public_checks": [asdict(c) for c in latest.results] if latest else [],
            "needs_input": latest.artifact.get("needs_input") if latest else None}


def catalog(store):
    with store.read_transaction() as db:
        rows = db.execute("SELECT o.* FROM work_orders o JOIN tabular_intakes i ON o.id=i.work_order_id ORDER BY o.rowid DESC")
        return {"orders": [dict(r) for r in rows]}


def _blind_check(artifact, profile, batch, control):
    from .tabular_analysis import verify_control

    report = verify_control(artifact, batch["standards"], control["signal"], control["factor"],
                            control["expected"], control["tolerance"], range_gate=profile["range_gate"])
    return {**report, "signal": control["signal"], "factor": control["factor"], "unit": profile["unit"]}


def submission_checks(store, order, artifact, *, approval=None):
    from .tabular_analysis import check

    if isinstance(artifact, dict) and set(artifact) == {"needs_input"}:
        question = artifact["needs_input"]
        if isinstance(question, str) and question.strip() and len(question) <= 1000:
            return [CheckResult("Information required", False, question)], None
    checks = check(artifact)
    if not all_passed(checks):
        return checks, None
    profile, batch = _intake(store, order.id)
    db = store.connection
    edition, control = _latest_control(db, order.id)
    if approval is None and _used(db, order.id, edition):
        raise WorkOrderError("A fresh blind control from the reviewer is required before submitting another candidate.")
    report = _blind_check(artifact, profile, batch, control)
    report.update(edition=edition, artifact_digest=canonical_digest(artifact), control_digest=canonical_digest(control))
    if approval is not None:
        saved = db.execute("SELECT report FROM tabular_reports WHERE work_order_id=? AND submission=?",
                           (order.id, approval)).fetchone()
        if not saved or report != json.loads(saved["report"]):
            raise WorkOrderError("The sealed control or verification report differs from the reviewed submission.")
    checks.append(CheckResult("Blind control", report["passed"],
                              "Within the pinned tolerance." if report["passed"] else
                              "The sealed control did not pass; numerical details are available to the reviewer."))
    return checks, report


def record_report(db, order_id, number, report):
    if report is not None:
        db.execute("INSERT INTO tabular_reports(work_order_id,submission,edition,report) VALUES (?,?,?,?)",
                   (order_id, number, report["edition"], canonical_json(report)))


def replace_control(store, order_id, reviewer, data):
    if set(data) != {"signal", "factor", "expected", "tolerance"}:
        raise ContextError("Supply a new control signal, factor, expected value and tolerance.")
    value = _control(**data)
    with store.transaction() as db:
        _intake(store, order_id)
        order = WorkOrders(store).get(order_id)
        edition, _ = _latest_control(db, order_id)
        if order.status not in ("in_progress", "open") or not _used(db, order_id, edition):
            raise WorkOrderError("Replace a used blind control after a failed or rejected submission.")
        previous = db.execute("SELECT value FROM tabular_controls WHERE work_order_id=?", (order_id,))
        if any(json.loads(row["value"])["signal"] == value["signal"] for row in previous):
            raise ContextError("Use a newly measured control with a different signal.")
        _new_control(db, order_id, edition + 1, value, reviewer)
        return {"id": order_id, "edition": edition + 1}


def reviewer_context(store, order):
    profile, batch = _intake(store, order.id)
    edition, _ = _latest_control(store.connection, order.id)
    latest = WorkOrders(store).submission(order.id)
    return {**profile, "needs_input": latest.artifact.get("needs_input") if latest else None,
            "protocol": tabular_files.load(store.connection, profile["protocol_digest"]),
            "csv_name": batch["csv_name"], "csv_digest": batch["csv_digest"],
            "standards_count": len(batch["standards"]), "unknown_count": len(batch["unknowns"]),
            "control_edition": edition, "control_renewal_required":
                order.status in ("in_progress", "open") and _used(store.connection, order.id, edition)}


def original(store, order_id, kind):
    profile, batch = _intake(store, order_id)
    if kind == "protocol":
        name, key = profile["protocol_name"], profile["protocol_digest"]
    elif kind == "readings":
        name, key = batch["csv_name"], batch["csv_digest"]
    else:
        raise NotFound("Unknown upload")
    return name, tabular_files.load(store.connection, key)


def run_original(store, order_id, run_id):
    row = store.connection.execute("SELECT receipt FROM tabular_runs WHERE id=? AND work_order_id=?", (run_id, order_id)).fetchone()
    if not row:
        raise NotFound("Unknown analysis batch.")
    receipt = json.loads(row["receipt"])
    return receipt["csv_name"], tabular_files.load(store.connection, receipt["csv_digest"])


def list_runs(db, order_id):
    rows = db.execute("SELECT id,receipt,created_at FROM tabular_runs WHERE work_order_id=? ORDER BY id DESC", (order_id,))
    return [{**json.loads(row["receipt"]), "id": row["id"], "created_at": row["created_at"]} for row in rows]


def run(store, order_id, reviewer, request):
    from .tabular_analysis import evaluate

    new_fields = {"csv_name", "csv", "control_expected", "control_tolerance"}
    if set(request) not in ({"submission"}, {"submission", *new_fields}) or type(request["submission"]) is not int:
        raise ContextError("Select a submission and either the original batch or a complete new batch with control.")
    with store.transaction() as db:
        orders = WorkOrders(store)
        order = orders.get(order_id)
        profile, batch = _intake(store, order_id)
        number = request["submission"]
        if order.status != "released" or number != order.released_submission:
            raise WorkOrderError("Approve this numbered submission before running it.")
        release = orders.submission(order_id, number)
        approval = db.execute("SELECT actor,note FROM events WHERE event='approved' AND work_order_id=? AND submission=?",
                              (order_id, number)).fetchone()
        if not (release and release.passed and approval and approval["note"] == release.artifact_digest
                == canonical_digest(release.artifact) and all_passed(release.results)):
            raise WorkOrderError("The approved artifact digest or verification checks could not be verified.")
        edition, control = _latest_control(db, order_id)
        report_row = db.execute("SELECT report FROM tabular_reports WHERE work_order_id=? AND submission=?",
                                (order_id, number)).fetchone()
        sealed = json.loads(report_row["report"]) if report_row else {}
        if (not sealed.get("passed") or sealed.get("edition") != edition
                or sealed.get("control_digest") != canonical_digest(control)
                or sealed.get("artifact_digest") != release.artifact_digest):
            raise WorkOrderError("The release does not match the reviewed control and source.")
        if new_fields <= request.keys():
            new_batch, new_control = _batch(request, profile["mapping"], profile["range_gate"])
            if new_batch["csv_digest"] == batch["csv_digest"] and new_control != control:
                raise WorkOrderError("This is the original batch; its control and tolerance are already pinned.")
            batch, control = new_batch, new_control
            control_digest = canonical_digest(control)
            db.execute("INSERT INTO tabular_batch_controls(work_order_id,csv_digest,control_digest) VALUES (?,?,?) "
                       "ON CONFLICT(work_order_id,csv_digest) DO NOTHING", (order_id, batch["csv_digest"], control_digest))
            pinned = db.execute("SELECT control_digest FROM tabular_batch_controls WHERE work_order_id=? AND csv_digest=?",
                                (order_id, batch["csv_digest"])).fetchone()
            if pinned["control_digest"] != control_digest:
                raise WorkOrderError("This batch already has a pinned control value and tolerance.")
            tabular_files.save(db, request["csv"])
        batch_digest = canonical_digest({"batch": batch, "control": control})
        prior = db.execute("SELECT id,receipt,created_at FROM tabular_runs WHERE work_order_id=? AND submission=? "
                           "AND batch_digest=? AND actor=?", (order_id, number, batch_digest, reviewer)).fetchone()
        if prior:
            return {**json.loads(prior["receipt"]), "id": prior["id"], "created_at": prior["created_at"]}
        qc = _blind_check(release.artifact, profile, batch, control)
        if new_fields <= request.keys():
            qc["source"] = "uploaded batch"
        else:
            qc.update(source="original batch" if edition == 1 else "replacement blind control", edition=edition)
        results = []
        if qc["passed"]:
            for row in batch["unknowns"]:
                try:
                    value = evaluate(release.artifact, batch["standards"], row["signal"], row["factor"],
                                     range_gate=profile["range_gate"])
                    reason = ""
                except ValueError as exc:
                    value, reason = None, str(exc)
                results.append({**row, "value": value, "unit": profile["unit"], "reason": reason})
        receipt = {"work_order_id": order_id, "submission": number, "actor": reviewer, "approved_by": approval["actor"],
                   "worker": release.worker, "artifact_digest": release.artifact_digest,
                   "protocol_digest": profile["protocol_digest"], "csv_name": batch["csv_name"],
                   "csv_digest": batch["csv_digest"], "batch_digest": batch_digest,
                   "standards": batch["standards"], "unit": profile["unit"], "range_gate": profile["range_gate"],
                   "experiment_id": order.experiment_id, "experiment_revision": order.experiment_revision,
                   "control": qc, "status": "estimated" if any(r["value"] is not None for r in results) else "withheld",
                   "results": results}
        cursor = db.execute("INSERT INTO tabular_runs(work_order_id,submission,batch_digest,actor,receipt) VALUES (?,?,?,?,?)",
                            (order_id, number, batch_digest, reviewer, canonical_json(receipt)))
        row = db.execute("SELECT created_at FROM tabular_runs WHERE id=?", (cursor.lastrowid,)).fetchone()
        return {**receipt, "id": cursor.lastrowid, "created_at": row["created_at"]}
