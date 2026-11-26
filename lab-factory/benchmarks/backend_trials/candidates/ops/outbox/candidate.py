"""A local SQLite dispatch outbox with durable completion receipts."""

import secrets
import sqlite3
from contextlib import closing


def _ensure_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS ob_jobs (
            job PRIMARY KEY NOT NULL,
            enqueue_key UNIQUE NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    # Time is compared in Python. Decimal text preserves the full integer range.
    db.execute("""
        CREATE TABLE IF NOT EXISTS ob_dispatch (
            job PRIMARY KEY REFERENCES ob_jobs(job) NOT NULL,
            worker, token TEXT, lease_start TEXT, lease_end TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ob_receipts (
            job PRIMARY KEY REFERENCES ob_jobs(job) NOT NULL,
            worker NOT NULL, token TEXT NOT NULL, result TEXT NOT NULL
        )
    """)


def _enqueue(db, request):
    job, key, payload = request["job"], request["key"], request["payload"]
    if key is None or not isinstance(payload, str):
        return {"ok": False}
    existing = db.execute(
        "SELECT job, enqueue_key, payload FROM ob_jobs WHERE job = ? OR enqueue_key = ?",
        (job, key),
    ).fetchall()
    if existing:
        return {"ok": existing == [(job, key, payload)]}
    db.execute("INSERT INTO ob_jobs VALUES (?, ?, ?)", (job, key, payload))
    db.execute("INSERT INTO ob_dispatch (job) VALUES (?)", (job,))
    return {"ok": True}


def _lease(db, request):
    job, worker = request["job"], request["worker"]
    now, ttl = request["now"], request["ttl"]
    if worker is None or type(now) is not int or type(ttl) is not int or ttl <= 0:
        return {"ok": False}
    dispatch = db.execute(
        "SELECT lease_end FROM ob_dispatch WHERE job = ?", (job,)
    ).fetchone()
    if dispatch is None or (dispatch[0] is not None and now < int(dispatch[0])):
        return {"ok": False}
    token = secrets.token_hex(32)
    db.execute(
        """UPDATE ob_dispatch SET worker = ?, token = ?, lease_start = ?, lease_end = ?
           WHERE job = ?""",
        (worker, token, str(now), str(now + ttl), job),
    )
    return {"ok": True, "token": token}


def _finish(db, request):
    job, worker = request["job"], request["worker"]
    now, token, payload = request["now"], request["token"], request["payload"]
    if type(now) is not int or not isinstance(token, str) or not isinstance(payload, str):
        return {"ok": False}
    receipt = db.execute(
        "SELECT worker, token, result FROM ob_receipts WHERE job = ?", (job,)
    ).fetchone()
    if receipt is not None:
        return {"ok": receipt == (worker, token, payload)}
    lease = db.execute(
        """SELECT lease_start, lease_end FROM ob_dispatch
           WHERE job = ? AND worker = ? AND token = ?""",
        (job, worker, token),
    ).fetchone()
    if lease is None or not int(lease[0]) <= now < int(lease[1]):
        return {"ok": False}
    db.execute("INSERT INTO ob_receipts VALUES (?, ?, ?, ?)", (job, worker, token, payload))
    db.execute("DELETE FROM ob_dispatch WHERE job = ?", (job,))
    return {"ok": True}


def _read(db, request):
    job = request["job"]
    receipt = db.execute("SELECT result FROM ob_receipts WHERE job = ?", (job,)).fetchone()
    if receipt is not None:
        return {"ok": True, "status": "done", "result": receipt[0], "payload": receipt[0]}
    dispatch = db.execute("SELECT lease_end FROM ob_dispatch WHERE job = ?", (job,)).fetchone()
    if dispatch is None:
        return {"ok": False}
    end = dispatch[0]
    now = request.get("now")
    queued = end is None or (now is not None and now >= int(end))
    return {"ok": True, "status": "queued" if queued else "leased"}


def solve(request):
    handlers = {"enqueue": _enqueue, "lease": _lease, "finish": _finish, "read": _read}
    try:
        handler = handlers[request["op"]]
        if request["job"] is None:
            return {"ok": False}
        with closing(sqlite3.connect(request["db"], timeout=30)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                # Reserve the writer before inspecting state, including on first open.
                db.execute("BEGIN IMMEDIATE")
                _ensure_tables(db)
                return handler(db, request)
    except (KeyError, TypeError, ValueError, OverflowError, sqlite3.Error):
        return {"ok": False}
