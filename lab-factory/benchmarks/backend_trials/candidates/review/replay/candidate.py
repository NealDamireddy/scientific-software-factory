"""SQLite-backed event replay for the local work-order review trial."""

from contextlib import closing
from hashlib import sha256
from os import PathLike
import sqlite3


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS review_events (
        order_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        action TEXT NOT NULL,
        actor TEXT NOT NULL,
        submission INTEGER,
        digest TEXT,
        PRIMARY KEY (order_id, revision)
    ) WITHOUT ROWID
"""


def _replay(db, order):
    state = {
        "status": None, "owner": None, "submission": 0, "digest": None,
        "events": [],
    }
    rows = db.execute(
        "SELECT action, actor, submission, digest FROM review_events "
        "WHERE order_id = ? ORDER BY revision",
        (order,),
    )
    for action, actor, submission, digest in rows:
        state["events"].append(action)
        if action == "create":
            state["status"] = "open"
        elif action == "claim":
            state.update(status="in_progress", owner=actor)
        elif action == "submit":
            state.update(status="in_review", submission=submission, digest=digest)
        elif action == "reject":
            state.update(status="open", owner=None)
        elif action == "approve":
            state["status"] = "released"
        else:
            raise ValueError("Unrecognized event in review history")
    return state


def _event_payload(req, state):
    """Return (submission, digest) for an allowed append, or None to deny."""
    op, role, status = req["op"], req["role"], state["status"]
    if op == "create" and role == "reviewer" and status is None:
        return (None, None)
    if op == "claim" and role == "agent" and status == "open":
        return (None, None)
    if op == "submit" and role == "agent" and status == "in_progress":
        artifact = req.get("artifact")
        if req["actor"] == state["owner"] and isinstance(artifact, str) and artifact.isascii():
            return (state["submission"] + 1, sha256(artifact.encode("ascii")).hexdigest())
    if op in ("approve", "reject") and role == "reviewer" and status == "in_review":
        target = req.get("submission")
        if type(target) is int and target == state["submission"]:
            return (target, None)
    return None


def solve(request):
    if not isinstance(request, dict):
        return {"ok": False}
    path, order, actor = (request.get(key) for key in ("db", "order", "actor"))
    if not isinstance(path, (str, PathLike)) or not path:
        return {"ok": False}
    if not all(isinstance(value, str) and value for value in (order, actor)):
        return {"ok": False}
    if request.get("role") not in ("reviewer", "agent"):
        return {"ok": False}
    op = request.get("op")
    if op not in ("read", "create", "claim", "submit", "reject", "approve"):
        return {"ok": False}

    try:
        with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as db:
            with db:
                # Writers reserve the append before reading the head of the stream.
                db.execute("BEGIN" if op == "read" else "BEGIN IMMEDIATE")
                if op == "read":
                    if not db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='review_events'"
                    ).fetchone():
                        return {"ok": False}
                else:
                    db.execute(_SCHEMA)
                state = _replay(db, order)
                if op == "read":
                    return {"ok": True, **state} if state["events"] else {"ok": False}
                payload = _event_payload(request, state)
                if payload is None:
                    return {"ok": False}
                revision = len(state["events"]) + 1
                db.execute(
                    "INSERT INTO review_events (order_id, revision, action, actor, submission, digest) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (order, revision, op, actor, *payload),
                )
                return {"ok": True}
    except (sqlite3.Error, OSError) as exc:
        return {"ok": False, "error": str(exc)}
