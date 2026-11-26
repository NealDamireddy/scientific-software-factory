"""A persistent job queue using SQLite transactions and per-claim lease tokens."""

import secrets
import sqlite3
from contextlib import closing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS lease_jobs (
    job TEXT PRIMARY KEY NOT NULL,
    enqueue_key TEXT UNIQUE NOT NULL,
    input_payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'leased', 'done')),
    worker TEXT,
    token TEXT,
    started INTEGER,
    expires INTEGER,
    finish_key TEXT,
    result TEXT
)
"""


def _handle(db, request):
    job, op = request["job"], request["op"]
    row = db.execute("SELECT * FROM lease_jobs WHERE job = ?", (job,)).fetchone()

    if op == "enqueue":
        key, payload = request["key"], request["payload"]
        if row is not None:
            return {"ok": row["enqueue_key"] == key and row["input_payload"] == payload}
        inserted = db.execute(
            """INSERT INTO lease_jobs (job, enqueue_key, input_payload, status)
               VALUES (?, ?, ?, 'queued') ON CONFLICT(enqueue_key) DO NOTHING""",
            (job, key, payload),
        )
        return {"ok": inserted.rowcount == 1}

    if row is None:
        return {"ok": False}

    status = row["status"]
    now = request.get("now")
    if op == "read":
        if status == "done":
            return {"ok": True, "status": status, "result": row["result"], "payload": row["result"]}
        if status == "leased" and now is not None and now >= row["expires"]:
            status = "queued"
        return {"ok": True, "status": status}

    worker = request["worker"]
    if op == "lease":
        if status == "done" or (status == "leased" and now < row["expires"]):
            return {"ok": False}
        token = secrets.token_urlsafe(32)
        db.execute(
            """UPDATE lease_jobs SET status = 'leased', worker = ?, token = ?,
                      started = ?, expires = ? WHERE job = ?""",
            (worker, token, now, now + request["ttl"], job),
        )
        return {"ok": True, "token": token}

    payload, key = request["payload"], request.get("key")
    if worker != row["worker"] or request["token"] != row["token"]:
        return {"ok": False}
    if status == "done":
        return {"ok": row["result"] == payload and row["finish_key"] == key}
    if status != "leased" or not row["started"] <= now < row["expires"]:
        return {"ok": False}
    db.execute(
        "UPDATE lease_jobs SET status = 'done', finish_key = ?, result = ? WHERE job = ?",
        (key, payload, job),
    )
    return {"ok": True}


def solve(request):
    """Apply one operation against a local database, publishing success after commit."""
    op = request.get("op")
    fields = {
        "enqueue": ("key", "payload"),
        "lease": ("worker",),
        "finish": ("worker", "token", "payload"),
        "read": (),
    }
    if op not in fields or not all(
        isinstance(request.get(field), str) for field in ("job", *fields[op])
    ):
        return {"ok": False}
    if op == "finish" and "key" in request and not isinstance(request["key"], str):
        return {"ok": False}
    if op in ("lease", "finish") or "now" in request:
        if type(request.get("now")) is not int:
            return {"ok": False}
    if op == "lease" and (type(request.get("ttl")) is not int or request["ttl"] <= 0):
        return {"ok": False}

    try:
        with closing(sqlite3.connect(request["db"], isolation_level=None, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            with db:
                # Reserve the writer before observing state. Competing processes
                # see the preceding commit even when racing to initialize the DB.
                db.execute("BEGIN IMMEDIATE")
                db.execute(_SCHEMA)
                return _handle(db, request)
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}
    except OverflowError:
        return {"ok": False, "error": "logical time exceeds SQLite integer range"}
