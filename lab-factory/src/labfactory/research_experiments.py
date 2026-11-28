"""Editable researcher records and their links to immutable worker requests."""
import json
import re
from uuid import UUID

from .context import ContextError, canonical_digest
from .store import NotFound
from .workorders import WorkOrderError


def text(value, field, limit=4000, *, optional=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or (not optional and not value.strip()):
        raise ContextError(f"Supply a valid {field} up to {limit} characters.")
    return value.strip()


def short_title(question):
    first = re.split(r"(?<=[.!?])\s+|\n", question.strip(), maxsplit=1)[0]
    compact = re.sub(r"^(?:please\s+)?(?:(?:have|ask) (?:the |a )?(?:worker|agent) (?:to )?)?"
                     r"(?:build|draft|create|write|generate|make|design)\s+(?:(?:a|an|the)\s+)?(?:new\s+)?",
                     "", first, flags=re.I)
    if compact != first:
        compact = re.sub(r"^(?:procedure|protocol|app|analysis app) (?:for|to) ", "", compact, flags=re.I)
        compact = compact.rstrip(".").strip()
        if compact:
            first = compact[:1].upper() + compact[1:]
    if len(first) <= 72:
        return first
    return (first[:71].rsplit(" ", 1)[0] or first[:71]) + "…"


def migrate_requests(db):
    rows = db.execute("""
        SELECT i.id,i.project_id,i.result,i.actor,i.request_digest FROM research_investigations i
        LEFT JOIN research_experiment_requests l ON l.request_id=i.id WHERE l.request_id IS NULL ORDER BY i.rowid
    """)
    for row in rows:
        question = json.loads(row["result"])["objective"]
        insert(db, row["id"], row["project_id"], short_title(question), question, row["actor"], row["request_digest"])
        link_request(db, row["id"], row["id"])


def insert(db, key, project, title, question, actor, stamp):
    db.execute("INSERT INTO research_experiments(id,project_id,title,question,actor,request_digest) VALUES(?,?,?,?,?,?)",
               (key, project, title, question, actor, stamp))


def link_request(db, key, experiment):
    db.execute("INSERT INTO research_experiment_requests(request_id,experiment_id) VALUES(?,?)", (key, experiment))


def attach(db, experiment, resource):
    db.execute("INSERT OR IGNORE INTO research_experiment_resources VALUES(?,?)", (experiment, resource))


def check_project(store, project):
    if not isinstance(project, str):
        raise ContextError("Choose a registered project.")
    root, revision = store.get_experiment(project)
    if store.connection.execute("SELECT 1 FROM research_investigations WHERE context_id=?", (project,)).fetchone():
        raise ContextError("Choose the project that owns this worker request.")
    return root, revision


def owned(db, project, experiment):
    if not isinstance(experiment, str) or not isinstance(project, str):
        raise ContextError("Choose an experiment in the selected project.")
    row = db.execute("SELECT * FROM research_experiments WHERE id=? AND project_id=?", (experiment, project)).fetchone()
    if row is None:
        raise NotFound("Unknown experiment in the selected project.")
    return row


def hypothesis(store, project):
    row = store.connection.execute("SELECT hypothesis FROM research_project_info WHERE project_id=?", (project,)).fetchone()
    return row["hypothesis"] if row else ""


def set_hypothesis(store, project, value):
    value = text(value, "hypothesis", optional=True)
    with store.transaction() as db:
        check_project(store, project)
        db.execute("""INSERT INTO research_project_info VALUES(?,?)
            ON CONFLICT(project_id) DO UPDATE SET hypothesis=excluded.hypothesis""", (project, value))
    return {"id": project, "hypothesis": value}


def summaries(db, project=None):
    query = "SELECT id,project_id,title,question,finding FROM research_experiments"
    if project is not None:
        query += " WHERE project_id=?"
    return [dict(row) for row in db.execute(query + " ORDER BY rowid DESC", (project,) if project is not None else ())]


def project_records(store, project, assets):
    db = store.connection
    catalog = {item["id"]: item for item in assets}
    records = {r["id"]: dict(r, requests=[], resources={}) for r in summaries(db, project)}
    requests = []
    for row in db.execute("""SELECT l.experiment_id,i.result FROM research_investigations i
            JOIN research_experiment_requests l ON l.request_id=i.id WHERE i.project_id=? ORDER BY i.rowid DESC""",
            (project,)):
        record = records[row["experiment_id"]]
        result = dict(json.loads(row["result"]), experiment_id=record["id"])
        record["requests"].append(result)
        requests.append(result)
        for item in result["resources"]:
            record["resources"].setdefault(item["id"], catalog.get(item["id"], item))
    for row in db.execute("""SELECT r.* FROM research_experiment_resources r JOIN research_experiments e
            ON e.id=r.experiment_id WHERE e.project_id=? ORDER BY r.rowid""", (project,)):
        item = catalog.get(row["resource_id"])
        if item:
            records[row["experiment_id"]]["resources"][item["id"]] = item
    for record in records.values():
        record["resources"] = list(record["resources"].values())
    return list(records.values()), requests


def create(store, actor, data):
    if not set(data) <= {"project_id", "request_id", "title", "question"}:
        raise ContextError("Use a project, request ID, title and question to create an experiment.")
    try:
        key = str(UUID(str(data.get("request_id"))))
    except ValueError:
        raise ContextError("Supply an experiment UUID.") from None
    project = data.get("project_id")
    question = text(data.get("question"), "question")
    title = text(data.get("title", short_title(question)), "title", 120)
    stamp = canonical_digest(data)
    with store.transaction() as db:
        check_project(store, project)
        row = db.execute("SELECT * FROM research_experiments WHERE id=?", (key,)).fetchone()
        if row:
            if row["actor"] != actor or row["request_digest"] != stamp:
                raise WorkOrderError("This experiment ID was already used with different inputs.")
        else:
            if db.execute("SELECT 1 FROM research_investigations WHERE id=?", (key,)).fetchone():
                raise WorkOrderError("This experiment ID was already used for a worker request.")
            insert(db, key, project, title, question, actor, stamp)
        from .investigations import resources
        records, _ = project_records(store, project, resources(store, project, include_history=True))
        return next(r for r in records if r["id"] == key)


def update(store, experiment, data):
    from .investigations import resources
    fields = {"title", "question", "finding"}
    if not set(data) <= fields | {"project_id", "attach_resource_id"} or len(data) < 2:
        raise ContextError("Choose an experiment field or resource to update.")
    project = data.get("project_id")
    with store.transaction() as db:
        owned(db, project, experiment)
        assets = resources(store, project, include_history=True)
        if "attach_resource_id" in data:
            key = data["attach_resource_id"]
            if not any(item["id"] == key and not item.get("next_order") for item in assets):
                raise NotFound("Unknown resource in the selected project.")
            attach(db, experiment, key)
        for field in fields.intersection(data):
            value = text(data[field], field, 120 if field == "title" else 4000, optional=field == "finding")
            db.execute(f"UPDATE research_experiments SET {field}=? WHERE id=?", (value, experiment))
        records, _ = project_records(store, project, assets)
        return next(r for r in records if r["id"] == experiment)
