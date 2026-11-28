"""Persist pinned project context, clarification turns and downloadable analysis applications."""

import hashlib
import json
from uuid import UUID

from . import analysis_context, offline_app, stage_plot
from .context import ContextError, canonical_digest, canonical_json
from .store import NotFound
from .workorders import WorkOrderError


PLOT_PREFIX = "PLOT-"
APP_PREFIX = "APP-"
PREFIXES = (APP_PREFIX, PLOT_PREFIX)


def _text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContextError(f"Supply {name} (up to {limit} characters).")
    return value.strip()


def _row(store, key):
    row = store.connection.execute("SELECT * FROM drift_requests WHERE id=?", (key,)).fetchone()
    if row is None:
        raise NotFound("Unknown analysis request.")
    return row


def _history(store, key):
    return [{**dict(row), "submission": json.loads(row["submission"])} for row in store.connection.execute(
        "SELECT turn,worker,submission,answer,answered_by,created_at FROM drift_turns WHERE request_id=? ORDER BY turn", (key,))]


def kind(key):
    return "offline_app" if key.startswith(APP_PREFIX) else "drift_plot"


def listing(store, status=None, prefix=None):
    sql = "SELECT id,objective,status,worker,turn FROM drift_requests WHERE id LIKE ?"
    params = [(prefix or "") + "%"]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = store.connection.execute(sql + " ORDER BY rowid", params)
    return [{**dict(row), "kind": kind(row["id"])} for row in rows]


def detail(store, key):
    with store.read_transaction():
        row = _row(store, key)
        return {**{k: row[k] for k in ("id", "actor", "objective", "status", "worker", "turn", "artifact_digest")},
                "contexts": json.loads(row["contexts"]), "history": _history(store, key)}


def create(store, actor, data, prefix=PLOT_PREFIX, *, datasets=(), procedure=None):
    if set(data) != {"request_id", "objective", "project"}:
        raise ContextError("Supply a request UUID, objective and project selection.")
    try:
        key = prefix + str(UUID(str(data["request_id"])))
    except ValueError:
        raise ContextError("Supply a valid request UUID.") from None
    objective = _text(data["objective"], "an analysis request", 4000)
    stamp = canonical_digest(data if not datasets and procedure is None else [data, datasets, procedure])
    with store.transaction() as db:
        prior = db.execute("SELECT actor,request_digest FROM drift_requests WHERE id=?", (key,)).fetchone()
        if prior:
            if prior["actor"] != actor or prior["request_digest"] != stamp:
                raise WorkOrderError("This request ID has already been used.")
        else:
            if prefix == PLOT_PREFIX and data["project"] == "stage-example":
                contexts = stage_plot.example_contexts()
            else:
                contexts = [analysis_context.snapshot(store, data["project"], include_project_documents=prefix == APP_PREFIX)]
            if procedure is not None:
                contexts[0]["procedure"] = procedure
            if len(datasets) == 1:
                contexts[0]["dataset"] = datasets[0]
            elif datasets:
                contexts[0]["datasets"] = datasets
            db.execute("INSERT INTO drift_requests(id,actor,request_digest,objective,contexts,status) "
                       "VALUES(?,?,?,?,?,'open')", (key, actor, stamp, objective, canonical_json(contexts)))
    return {"id": key}


def claim(store, key, worker):
    if not isinstance(worker, str) or not worker.strip() or len(worker) > 160:
        raise WorkOrderError("Supply a worker name.")
    with store.transaction() as db:
        row = _row(store, key)
        if row["status"] == "open":
            db.execute("UPDATE drift_requests SET status='in_progress',worker=? WHERE id=?", (worker, key))
        elif row["status"] != "in_progress" or worker != row["worker"]:
            raise WorkOrderError("This analysis request is no longer available to claim.")
    return {"id": key, "status": "in_progress", "claim_id": row["turn"]}


def answer(store, key, actor, data):
    if set(data) != {"turn", "answer"} or type(data["turn"]) is not int:
        raise ContextError("Supply the question turn number and an answer.")
    message = _text(data["answer"], "your answer", 6000)
    with store.transaction() as db:
        row = _row(store, key)
        prior = db.execute("SELECT answer,answered_by FROM drift_turns WHERE request_id=? AND turn=?",
                           (key, data["turn"])).fetchone()
        if prior and prior["answer"] == message and prior["answered_by"] == actor:
            return {"id": key}
        if row["status"] != "needs_input" or data["turn"] != row["turn"]:
            raise WorkOrderError("This question has moved on. Refresh the request.")
        db.execute("UPDATE drift_turns SET answer=?,answered_by=? WHERE request_id=? AND turn=?",
                   (message, actor, key, data["turn"]))
        db.execute("UPDATE drift_requests SET turn=turn+1,status='open',worker=NULL WHERE id=?", (key,))
    return {"id": key}


def submit(store, key, worker, artifact):
    field = "app" if key.startswith(APP_PREFIX) else "plot"
    if not isinstance(artifact, dict) or set(artifact) != {"turn", field} or type(artifact["turn"]) != int:
        raise WorkOrderError("Supply the current turn and an analysis decision.")
    payload, turn = artifact[field], artifact["turn"]
    with store.transaction() as db:
        row = _row(store, key)
        history = _history(store, key)
        if history and history[-1]["turn"] == turn and history[-1]["worker"] == worker and history[-1]["submission"] == payload:
            return {"status": row["status"], "turn": turn}
        if row["status"] != "in_progress" or row["worker"] != worker or row["turn"] != turn:
            raise WorkOrderError("Stale turn or invalid analysis claim.")
        contexts = json.loads(row["contexts"])
        try:
            if field == "app":
                offline_app.validate(payload)
            else:
                stage_plot.validate(payload, contexts)
        except ValueError as exc:
            return {"retry": str(exc)}
        html = digest = None
        state = "needs_input" if payload["question"] else "ready"
        if state == "ready" and field == "app":
            html = offline_app.package(payload["html"])
        elif state == "ready":
            html = stage_plot.render(key, row["objective"], payload, contexts, history, worker)
        if html is not None:
            digest = hashlib.sha256(html.encode()).hexdigest()
        db.execute("INSERT INTO drift_turns(request_id,turn,worker,submission) VALUES(?,?,?,?)",
                   (key, turn, worker, canonical_json(payload)))
        db.execute("UPDATE drift_requests SET status=?,html=?,artifact_digest=? WHERE id=?", (state, html, digest, key))
    return {"status": state, "turn": turn}


def download(store, key):
    row = _row(store, key)
    if row["status"] != "ready" or hashlib.sha256(row["html"].encode()).hexdigest() != row["artifact_digest"]:
        raise WorkOrderError("A complete download with a matching digest is unavailable.")
    return row["html"]
