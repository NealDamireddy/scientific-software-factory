"""Versioned protocol + readings intake, sealed control verification, and release receipts."""

from dataclasses import asdict
import csv
import io
import json
import math
from uuid import UUID, uuid4

from lab_codex_worker.skills import pin_skills

from . import analysis_context, references, research_experiments, tabular_files
from .tabular_analysis import LANGUAGE_PROFILES
from .artifacts import render_artifact
from .checks import CheckResult, all_passed
from .context import ContextError, Document, Experiment, Lab, canonical_digest, canonical_json, to_dict
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


def _stored_control(db, order_id, edition=None):
    query = "SELECT edition,value FROM tabular_controls WHERE work_order_id=?"
    if edition is None:
        row = db.execute(query + " ORDER BY edition DESC LIMIT 1", (order_id,)).fetchone()
    else:
        row = db.execute(query + " AND edition=?", (order_id, edition)).fetchone()
    if row is None:
        raise WorkOrderError("The sealed control edition is missing.")
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
    fields += tuple(key for key in ("allowed_languages", "verifiers", "research_context") if key in profile)
    if "procedure" in profile:
        fields += ("procedure",)
    spec = {**{k: profile[k] for k in fields}, "standards": batch["standards"]}
    if "skills" in profile:
        spec["skill_versions"] = [{"id": skill["id"], "version": skill["version"]} for skill in profile["skills"]]
    return spec


def _experiment(exp_id, profile, batch):
    document = Document("analysis-specification", "note", "Analysis input specification",
                        "Reviewer upload", canonical_json(_public_spec(profile, batch)))
    return Experiment(exp_id, LAB.id, profile["objective"], profile["objective"], (), (document,))


def _verified_release(orders, order):
    number = order.released_submission
    if order.status != "released" or number is None:
        raise WorkOrderError(f"Work order {order.id} has no released submission.")
    release = orders.submission(order.id, number)
    approval = orders.db.execute(
        "SELECT actor,note FROM events WHERE event='approved' AND work_order_id=? AND submission=?",
        (order.id, number),
    ).fetchone()
    if not (approval and approval["note"] == release.artifact_digest == canonical_digest(release.artifact)
            and release.passed and all_passed(release.results)):
        raise WorkOrderError("The approved artifact digest or verification checks could not be verified.")
    return release, approval["actor"]


def procedure_pin(store, order_id):
    orders = WorkOrders(store)
    order = orders.get(_text(order_id, "a procedure work order ID", 100))
    if order.kind != "procedure":
        raise WorkOrderError("Select a released procedure work order.")
    release, _ = _verified_release(orders, order)
    return {"order_id": order.id, "submission": release.number, "artifact_digest": release.artifact_digest,
            "experiment_id": order.experiment_id, "experiment_revision": order.experiment_revision,
            "lab_id": order.lab_id, "lab_revision": order.lab_revision}


def _procedure_context(store, pin):
    lab, _ = store.get_lab(pin["lab_id"], pin["lab_revision"])
    experiment, _ = store.get_experiment(pin["experiment_id"], pin["experiment_revision"])
    release = WorkOrders(store).submission(pin["order_id"], pin["submission"])
    if pin["artifact_digest"] != canonical_digest(release.artifact):
        raise WorkOrderError("The procedure instructions differ from the released artifact digest.")
    return {"lab": to_dict(lab), "experiment": to_dict(experiment),
            "instructions": render_artifact("procedure", release.artifact)}


def create_order(store, reviewer, request):
    required = {"objective", "csv_name", "csv", "unit", "mapping",
                "control_expected", "control_tolerance"}
    if not required <= set(request) <= required | {"protocol_name", "protocol", "research_context", "allowed_languages", "range_gate", "reference_ids", "request_id", "procedure_order_id", "skills", "project_id", "research_experiment_id"}:
        raise ContextError("Supply protocol and CSV uploads, an objective, column mapping, result unit and control settings.")
    key = request.get("request_id")
    if key is not None:
        try:
            key = str(UUID(str(key)))
        except ValueError:
            raise ContextError("Use a UUID as the analysis request ID.") from None
    objective = _text(request["objective"], "an objective", 1000)
    unit = _text(request["unit"], "a result unit and basis", 100)
    protocol = protocol_name = None
    if "protocol" in request or "protocol_name" in request:
        protocol = _text(request.get("protocol"), "a text or Markdown protocol", 32 * 1024)
        protocol_name = _filename(request.get("protocol_name"), (".txt", ".md", ".markdown"))
    elif "research_context" not in request:
        raise ContextError("Supply a protocol or select a saved research experiment.")
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
                   protocol_name=protocol_name, protocol_digest=tabular_files.digest(protocol) if protocol else None, references=sources)
    if "skills" in request:
        try:
            profile["skills"] = pin_skills(request["skills"])
        except ValueError as exc:
            raise ContextError(str(exc)) from exc
    if "allowed_languages" in request:
        languages = request["allowed_languages"]
        if (not isinstance(languages, list) or not languages
                or any(not isinstance(name, str) or name not in LANGUAGE_PROFILES for name in languages)
                or len(set(languages)) != len(languages)):
            raise ContextError("Provide a nonempty ordered list of unique allowed_languages from: "
                               + ", ".join(LANGUAGE_PROFILES))
        profile["allowed_languages"] = languages
        profile["verifiers"] = {name: LANGUAGE_PROFILES[name].verifier for name in languages}
    exp_id = PREFIX + uuid4().hex
    with store.transaction() as db:
        if key is not None:
            fingerprint = canonical_digest({k: v for k, v in request.items() if k != "request_id"})
            prior = db.execute("SELECT work_order_id,digest FROM tabular_requests WHERE actor=? AND request_id=?",
                               (reviewer, key)).fetchone()
            if prior is not None:
                if fingerprint != prior["digest"]:
                    raise WorkOrderError("This request ID was already used for a different upload.")
                return {"id": prior["work_order_id"]}
        if "research_context" in request:
            evidence = analysis_context.snapshot(store, request["research_context"])
            if "project_id" in request and evidence["experiment"]["id"] != request["project_id"]:
                raise ContextError("The selected research context belongs to another project.")
            profile["research_context"] = evidence
        if "procedure_order_id" in request:
            profile["procedure"] = procedure_pin(store, request["procedure_order_id"])
        if "project_id" in request:
            project_id = _text(request["project_id"], "a registered project ID", 500)
            project, revision = store.get_experiment(project_id)
            if "procedure" in profile:
                owner = profile["procedure"]["experiment_id"]
                child = db.execute("SELECT project_id FROM research_investigations WHERE context_id=?", (owner,)).fetchone()
                if (child["project_id"] if child else owner) != project.id:
                    raise WorkOrderError("The selected procedure belongs to another project.")
            profile["project"] = {"id": project.id, "revision": revision.number}
        if "research_experiment_id" in request:
            experiment = request["research_experiment_id"]
            research_experiments.owned(db, request.get("project_id"), experiment)
            profile["research_experiment_id"] = experiment
        # Only public inputs go in the experiment. Keep the private batch sealed in the intake.
        exp = _experiment(exp_id, profile, batch)
        profile["intake_digest"] = canonical_digest({"profile": profile, "batch": batch})
        if protocol:
            tabular_files.save(db, protocol)
        tabular_files.save(db, request["csv"])
        store.put_lab(LAB)
        store.put_experiment(exp, allow_unassigned=True)
        order = WorkOrders(store).create(exp_id, "analysis_app", objective, actor=reviewer, tabular_upload=True)
        db.execute("INSERT INTO tabular_intakes(work_order_id,profile,batch) VALUES (?,?,?)",
                   (order.id, canonical_json(profile), canonical_json(batch)))
        if "research_experiment_id" in profile:
            research_experiments.attach(db, experiment, order.id)
            research_experiments.attach(db, experiment, order.id + "/uploads/readings")
            if "procedure" in profile:
                research_experiments.attach(db, experiment, profile["procedure"]["order_id"])
        _new_control(db, order.id, 1, control, reviewer)
        if key is not None:
            db.execute("INSERT INTO tabular_requests(actor,request_id,digest,work_order_id) VALUES (?,?,?,?)",
                       (reviewer, key, fingerprint, order.id))
        return {"id": order.id}


def public_context(store, order):
    profile, batch = _intake(store, order.id)
    public = _public_spec(profile, batch)
    if "skills" in profile:
        public["skills"] = profile["skills"]
    if "procedure" in public:
        public["procedure_context"] = _procedure_context(store, public["procedure"])
    latest = WorkOrders(store).submission(order.id)
    edition, _ = _stored_control(store.connection, order.id)
    return {**public, "protocol": _protocol(store, profile),
            "awaiting_fresh_control": order.status in ("open", "in_progress") and _used(store.connection, order.id, edition),
            "last_public_checks": [asdict(c) for c in latest.results] if latest else [],
            "needs_input": latest.artifact.get("needs_input") if latest else None}


def catalog(store):
    with store.read_transaction() as db:
        rows = db.execute("SELECT o.* FROM work_orders o JOIN tabular_intakes i ON o.id=i.work_order_id ORDER BY o.rowid DESC")
        return {"orders": [dict(r) for r in rows]}


def _blind_check(artifact, profile, batch, control):
    from .tabular_analysis import verify_control

    language = artifact.get("language", "python")
    verifier = profile.get("verifiers", {}).get(language)
    if verifier is not None and (language not in LANGUAGE_PROFILES or LANGUAGE_PROFILES[language].verifier != verifier):
        raise WorkOrderError("The pinned analysis verifier is unavailable.")
    report = verify_control(artifact, batch["standards"], control["signal"], control["factor"],
                            control["expected"], control["tolerance"], range_gate=profile["range_gate"])
    if verifier is not None:
        report.update(language=language, verifier=verifier)
    return {**report, "signal": control["signal"], "factor": control["factor"], "unit": profile["unit"]}


def submission_checks(store, order, artifact, *, approval=None):
    from .tabular_analysis import check

    if isinstance(artifact, dict) and set(artifact) == {"needs_input"}:
        question = artifact["needs_input"]
        if isinstance(question, str) and question.strip() and len(question) <= 1000:
            return [CheckResult("Information required", False, question)], None
    profile, batch = _intake(store, order.id)
    allowed = profile.get("allowed_languages")
    if isinstance(artifact, dict) and (allowed is not None or "language" in artifact):
        if artifact.get("language") not in (allowed or ["python"]):
            return [CheckResult("Analysis language", False,
                                "Select a permitted language: " + ", ".join(allowed or ["python"]))], None
    checks = check(artifact)
    if not all_passed(checks):
        return checks, None
    db = store.connection
    edition, control = _stored_control(db, order.id)
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
        edition, _ = _stored_control(db, order_id)
        if order.status not in ("in_progress", "open") or not _used(db, order_id, edition):
            raise WorkOrderError("Replace a used blind control after a failed or rejected submission.")
        previous = db.execute("SELECT value FROM tabular_controls WHERE work_order_id=?", (order_id,))
        if any(json.loads(row["value"])["signal"] == value["signal"] for row in previous):
            raise ContextError("Use a newly measured control with a different signal.")
        _new_control(db, order_id, edition + 1, value, reviewer)
        return {"id": order_id, "edition": edition + 1}


def reviewer_context(store, order):
    profile, batch = _intake(store, order.id)
    edition, _ = _stored_control(store.connection, order.id)
    latest = WorkOrders(store).submission(order.id)
    return {**profile, "needs_input": latest.artifact.get("needs_input") if latest else None,
            "protocol": _protocol(store, profile),
            "csv_name": batch["csv_name"], "csv_digest": batch["csv_digest"],
            "standards_count": len(batch["standards"]), "unknown_count": len(batch["unknowns"]),
            "control_edition": edition, "control_renewal_required":
                order.status in ("in_progress", "open") and _used(store.connection, order.id, edition)}


def _protocol(store, profile):
    digest = profile["protocol_digest"]
    return tabular_files.load(store.connection, digest) if digest else None


def original(store, order_id, kind):
    profile, batch = _intake(store, order_id)
    if kind == "protocol":
        if not profile["protocol_digest"]:
            raise NotFound("No protocol file was uploaded for this analysis.")
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


def _execution_batch(db, order_id, profile, original, request):
    if "csv" in request:
        uploaded, uploaded_control = _batch(request, profile["mapping"], profile["range_gate"])
        if uploaded["csv_digest"] != original["csv_digest"]:
            key = (order_id, uploaded["csv_digest"])
            fingerprint = canonical_digest(uploaded_control)
            db.execute("INSERT INTO tabular_batch_controls(work_order_id,csv_digest,control_digest) VALUES (?,?,?) "
                       "ON CONFLICT(work_order_id,csv_digest) DO NOTHING", (*key, fingerprint))
            pinned = db.execute("SELECT control_digest FROM tabular_batch_controls WHERE work_order_id=? AND csv_digest=?",
                                key).fetchone()
            if pinned["control_digest"] != fingerprint:
                raise WorkOrderError("This batch already has a pinned control value and tolerance.")
            tabular_files.save(db, request["csv"])
            return uploaded, uploaded_control, {"source": "uploaded batch"}

    # Later holdouts qualify revised programs. Only edition 1 belongs to the collected batch.
    _, original_control = _stored_control(db, order_id, 1)
    if "csv" in request and uploaded_control != original_control:
        raise WorkOrderError("This is the original batch; its control and tolerance are already pinned.")
    return original, original_control, {"source": "original batch", "edition": 1}


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
        release, approved_by = _verified_release(orders, order)
        edition, control = _stored_control(db, order_id)
        report_row = db.execute("SELECT report FROM tabular_reports WHERE work_order_id=? AND submission=?",
                                (order_id, number)).fetchone()
        sealed = json.loads(report_row["report"]) if report_row else {}
        if (not sealed.get("passed") or sealed.get("edition") != edition
                or sealed.get("control_digest") != canonical_digest(control)
                or sealed.get("artifact_digest") != release.artifact_digest):
            raise WorkOrderError("The release does not match the reviewed control and source.")
        batch, control, qc_source = _execution_batch(db, order_id, profile, batch, request)
        batch_digest = canonical_digest({"batch": batch, "control": control})
        prior = db.execute("SELECT id,receipt,created_at FROM tabular_runs WHERE work_order_id=? AND submission=? "
                           "AND batch_digest=? AND actor=?", (order_id, number, batch_digest, reviewer)).fetchone()
        if prior:
            return {**json.loads(prior["receipt"]), "id": prior["id"], "created_at": prior["created_at"]}
        qc = _blind_check(release.artifact, profile, batch, control)
        qc.update(qc_source)
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
        receipt = {"work_order_id": order_id, "submission": number, "actor": reviewer, "approved_by": approved_by,
                   "worker": release.worker, "artifact_digest": release.artifact_digest,
                   "protocol_digest": profile["protocol_digest"], "csv_name": batch["csv_name"],
                   "csv_digest": batch["csv_digest"], "batch_digest": batch_digest,
                   "standards": batch["standards"], "unit": profile["unit"], "range_gate": profile["range_gate"],
                   "experiment_id": order.experiment_id, "experiment_revision": order.experiment_revision,
                   "release_control_edition": edition, "control": qc,
                   "status": "estimated" if any(r["value"] is not None for r in results) else "withheld",
                   "results": results}
        if evidence := profile.get("research_context"):
            receipt["research_context"] = {scope: {key: record[key] for key in ("id", "revision", "digest")}
                                           for scope, record in evidence.items()}
        receipt["language"] = release.artifact.get("language", "python")
        if "procedure" in profile:
            receipt["procedure"] = profile["procedure"]
        cursor = db.execute("INSERT INTO tabular_runs(work_order_id,submission,batch_digest,actor,receipt) VALUES (?,?,?,?,?)",
                            (order_id, number, batch_digest, reviewer, canonical_json(receipt)))
        row = db.execute("SELECT created_at FROM tabular_runs WHERE id=?", (cursor.lastrowid,)).fetchone()
        return {**receipt, "id": cursor.lastrowid, "created_at": row["created_at"]}
