"""Transactional first drafts and source replies, independent of any frontend."""

from dataclasses import asdict
import json
import re

from . import method_drafter, procedure_drafts, source_drafter
from .artifacts import parse_artifact
from .checks import check_artifact
from .context import ContextError, canonical_digest, canonical_json, experiment_from_dict, lab_from_dict
from .store import NotFound
from .workorders import WorkOrderError, WorkOrders


WORKER = "Lab Factory method drafter"


def _text(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip() or not value.isprintable():
        raise ContextError(f"{field} must be nonempty, printable text")
    return value


def _row(store, order_id):
    row = store.connection.execute("SELECT * FROM automatic_procedures WHERE work_order_id=?", (order_id,)).fetchone()
    if row is None:
        raise NotFound(f"unknown automatic procedure draft {order_id}")
    return row


def detail(store, order_id):
    row = _row(store, order_id)
    orders = WorkOrders(store)
    order = orders.get(order_id)
    submission = orders.submission(order_id)
    lab, exp = orders.pinned_context(order_id)
    linked = procedure_drafts.info(store, order_id)
    question = submission.artifact.get("needs_input") if submission else None
    state = order.status if submission else "drafting"
    if linked["next_order"]:
        state = "superseded"
    elif state == "in_progress" and question:
        state = "needs_input"
    plan = json.loads(row["plan"])
    sources = procedure_drafts.review_passages(lab, exp, submission.artifact) if submission else []
    if question and row["question_step"] is not None:
        ref = plan[row["question_step"]]
        evidence = [ref, *ref.get("supplements", [])]
        sources = procedure_drafts.review_passages(lab, exp, {"steps": [{"evidence": evidence}]})
    assessment = store.connection.execute("SELECT plan,input_kind FROM procedure_decision_evidence WHERE work_order_id=?",
                                          (order_id,)).fetchone()
    return {
        "decision_evidence": json.loads(assessment["plan"]) if assessment and assessment["plan"] else [],
        "input_kind": assessment["input_kind"] if assessment else None,
        "documents": [{"id": d.id, "title": d.title, "kind": d.kind} for d in (*exp.documents, *lab.documents)],
        "order": asdict(order), "state": state, "question": question,
        "question_step": None if row["question_step"] is None else row["question_step"] + 1,
        "previous_order": linked["previous_order"], "next_order": linked["next_order"],
        "submission": asdict(submission) if submission else None,
        "sources": sources,
    }


def _cached(store, actor, data, previous):
    request_id = _text(data, "request_id")
    if len(request_id) > 128:
        raise ContextError("request_id exceeds 128 characters")
    try:
        fingerprint = canonical_digest({"request": data, "previous": previous})
    except (ValueError, RecursionError) as exc:
        raise ContextError("The request must be valid finite JSON.") from exc
    row = store.connection.execute("SELECT * FROM automatic_procedures WHERE actor=? AND request_id=?",
                                   (actor, request_id)).fetchone()
    if row and row["request_digest"] != fingerprint:
        raise WorkOrderError("That request_id was already used for different input.")
    return fingerprint, row["work_order_id"] if row else None


def _register_author(store, order, actor, data, fingerprint):
    store.connection.execute(
        "INSERT INTO automatic_procedures(work_order_id,actor,request_id,request_digest,plan) VALUES (?,?,?,?,?)",
        (order.id, actor, data["request_id"], fingerprint, "[]"))
    source_drafter.register(store, order.id)
    return detail(store, order.id)


def _compile(store, order, actor, data, fingerprint, document_id, *, previous_plan=None, replace_at=None):
    orders = WorkOrders(store)
    lab, experiment = orders.pinned_context(order.id)
    if document_id is None and (lab.documents or experiment.documents) and not method_drafter.applicable_methods(lab, experiment):
        return _register_author(store, order, actor, data, fingerprint)
    method, question = method_drafter.select_method(lab, experiment, document_id)
    plan = []
    if method:
        plan, question = method_drafter.method_lines(lab, experiment, method)
    if question and previous_plan:
        # Keep the original unresolved passage if the clarification also needs revision.
        plan = previous_plan
    elif replace_at is not None:
        if len(plan) == 1:
            supplemented = method_drafter.supplement_setting(lab, experiment, previous_plan[replace_at], plan[0])
            if supplemented:
                plan = [supplemented]
        plan = previous_plan[:replace_at] + plan + previous_plan[replace_at + 1:]
    blocked = replace_at if question and previous_plan else None
    if not question and len(plan) > 128:
        question = "Can you supply a focused method with at most 128 instructions?"
        blocked = None
    if not question:
        candidate, blocked, question = method_drafter.build_candidate(lab, experiment, plan)
        if question and previous_plan == [] and replace_at is None:
            # The first reply to an empty intake can supply sources rather than a step-by-step method.
            return _register_author(store, order, actor, data, fingerprint)
    if not question:
        artifact = parse_artifact("procedure", candidate)
        checks = check_artifact(artifact, lab, experiment)
        checks += procedure_drafts.evidence_checks(artifact, lab, experiment, required=True)
        failure = next((check for check in checks if not check.passed), None)
        if failure:
            step = re.match(r"step (\d+):", failure.name)
            blocked = int(step[1]) - 1 if step else None
            question = f"{failure.detail}. What corrected method instruction should be used?"
    if question:
        question = "".join(ch if ch.isprintable() else " " for ch in question)
    orders.claim(order.id, WORKER)
    orders.submit(order.id, WORKER, {"needs_input": question} if question else candidate)
    store.connection.execute(
        "INSERT INTO automatic_procedures(work_order_id,actor,request_id,request_digest,plan,question_step) "
        "VALUES (?,?,?,?,?,?)", (order.id, actor, data["request_id"], fingerprint, canonical_json(plan), blocked))
    return detail(store, order.id)


def start(store, actor, data):
    keys = set(data) - {"request_id", "method_id"}
    if keys not in ({"experiment_id"}, {"lab", "experiment"}):
        raise ContextError("Supply experiment_id or a lab and experiment context snapshot.")
    method_id = _text(data, "method_id") if "method_id" in data else None
    with store.transaction():
        fingerprint, cached = _cached(store, actor, data, None)
        if cached:
            return detail(store, cached)
        if "experiment_id" in data:
            experiment_id = _text(data, "experiment_id")
        else:
            lab = lab_from_dict(data["lab"])
            experiment = experiment_from_dict(data["experiment"], allow_unassigned=True)
            if experiment.lab_id != lab.id:
                raise ContextError("The experiment must reference the supplied lab.")
            # Saving inline context must never replace a newer, separately edited record.
            for get, record in ((store.get_lab, lab), (store.get_experiment, experiment)):
                try:
                    current, _ = get(record.id)
                except NotFound:
                    continue
                if current != record:
                    raise WorkOrderError(f"Context {record.id} already exists with different content. "
                                         "Save the intended revision explicitly and start by experiment_id.")
            store.put_lab(lab)
            store.put_experiment(experiment, allow_unassigned=True)
            experiment_id = experiment.id
        order = procedure_drafts.create(store, experiment_id, actor)
        return _compile(store, order, actor, data, fingerprint, method_id)


def answer(store, actor, order_id, data):
    keys = set(data) - {"request_id"}
    if keys not in ({"title", "text"}, {"method_id"}):
        raise ContextError("Supply a source title and text, or select a pinned method_id.")
    method_id = _text(data, "method_id") if "method_id" in data else None
    with store.transaction():
        fingerprint, cached = _cached(store, actor, data, order_id)
        if cached:
            return detail(store, cached)
        original = _row(store, order_id)
        orders = WorkOrders(store)
        parent = orders.get(order_id)
        if detail(store, order_id)["state"] != "needs_input":
            raise WorkOrderError("This order has no pending question. Read its current state.")
        exp, exp_rev = store.get_experiment(parent.experiment_id)
        _, lab_rev = store.get_lab(parent.lab_id)
        if (exp_rev.number, lab_rev.number) != (parent.experiment_revision, parent.lab_revision):
            raise WorkOrderError("The pinned context has changed. Start from the current experiment.")
        if method_id:
            lab, experiment = orders.pinned_context(order_id)
            doc, problem = method_drafter.select_method(lab, experiment, method_id)
            if not doc:
                raise ContextError(problem)
            new = procedure_drafts.create(store, exp.id, actor, previous=order_id)
            return _compile(store, new, actor, data, fingerprint, method_id)
        new_id = procedure_drafts.add_source(store, order_id, actor, _text(data, "title"), data["text"])
        if parent.worker == source_drafter.WORKER:
            return _register_author(store, orders.get(new_id), actor, data, fingerprint)
        _, revised = orders.pinned_context(new_id)
        return _compile(store, orders.get(new_id), actor, data, fingerprint, revised.documents[-1].id,
                        previous_plan=json.loads(original["plan"]), replace_at=original["question_step"])
