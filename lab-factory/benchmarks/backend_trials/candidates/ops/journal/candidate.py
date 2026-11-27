"""An append-only SQLite journal for a queue driven by caller-supplied time."""

import json
import secrets
import sqlite3
from contextlib import closing


def _replay(db, job):
    # The enqueue, latest lease, and finish are sufficient to decide the next event.
    events = {}
    for kind, key, body in db.execute(
        "SELECT kind, enqueue_key, body FROM queue_events WHERE job = ? ORDER BY seq",
        (job,),
    ):
        event = json.loads(body)
        if kind == "enqueue":
            event["key"] = key
        events[kind] = event
    return events


def _append(db, job, kind, body, enqueue_key=None):
    db.execute(
        "INSERT INTO queue_events (job, kind, body, enqueue_key) VALUES (?, ?, ?, ?)",
        (job, kind, json.dumps(body), enqueue_key),
    )


def _operate(db, request):
    job, op = request["job"], request["op"]
    if not isinstance(job, str):
        return {"ok": False}
    events = _replay(db, job)
    enqueued = events.get("enqueue")
    if op == "enqueue":
        key, payload = request["key"], request["payload"]
        if not isinstance(key, str) or not isinstance(payload, str):
            return {"ok": False}
        if enqueued is not None:
            return {"ok": enqueued == {"key": key, "payload": payload}}
        _append(db, job, op, {"payload": payload}, enqueue_key=key)
        return {"ok": True}
    if enqueued is None:
        return {"ok": False}

    lease, finish = events.get("lease"), events.get("finish")
    now = request.get("now")
    if (op != "read" or now is not None) and type(now) is not int:
        return {"ok": False}
    expired = lease is not None and now is not None and now >= lease["expires"]

    if op == "read":
        if finish is not None:
            return {
                "ok": True,
                "status": "done",
                "result": finish["payload"],
                "payload": finish["payload"],
            }
        status = "queued" if lease is None or expired else "leased"
        return {"ok": True, "status": status, "payload": enqueued["payload"]}

    worker = request["worker"]
    if not isinstance(worker, str):
        return {"ok": False}
    if op == "lease":
        ttl = request["ttl"]
        if type(ttl) is not int or ttl <= 0:
            return {"ok": False}
        if finish is not None or (lease is not None and not expired):
            return {"ok": False}
        token = secrets.token_hex(24)
        lease_event = {"worker": worker, "token": token, "start": now, "expires": now + ttl}
        _append(db, job, op, lease_event)
        return {"ok": True, "token": token, "payload": enqueued["payload"]}

    if op == "finish":
        token, payload = request["token"], request["payload"]
        if not isinstance(payload, str) or lease is None:
            return {"ok": False}
        if worker != lease["worker"] or token != lease["token"]:
            return {"ok": False}
        result = {"payload": payload, "key": request.get("key")}
        if finish is not None:
            return {"ok": finish == result}
        if now < lease["start"] or expired:
            return {"ok": False}
        _append(db, job, op, result)
        return {"ok": True}
    return {"ok": False}


def solve(request):
    try:
        with closing(sqlite3.connect(request["db"], isolation_level=None)) as db:
            if request["op"] == "read":
                # Replay uses a single SELECT and sees one committed snapshot.
                return _operate(db, request)
            with db:
                # Serialize decisions even when two processes initialize an empty file.
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS queue_events ("
                    "seq INTEGER PRIMARY KEY, job TEXT NOT NULL, kind TEXT NOT NULL, "
                    "body TEXT NOT NULL, enqueue_key TEXT UNIQUE)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS queue_job_seq ON queue_events(job, seq)"
                )
                return _operate(db, request)
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "conflicting journal entry"}
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "invalid request or journal data"}
    except sqlite3.Error as error:
        return {"ok": False, "error": str(error)}
