"""Transactional SQLite implementation of the work-order review contract."""

import hashlib
import sqlite3
from contextlib import closing


def _create_tables(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS review_orders (
            order_id PRIMARY KEY NOT NULL,
            status TEXT NOT NULL,
            owner TEXT,
            submission INTEGER NOT NULL DEFAULT 0,
            digest TEXT,
            revision INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS review_events (
            order_id NOT NULL,
            revision INTEGER NOT NULL,
            operation TEXT NOT NULL,
            actor TEXT NOT NULL,
            submission INTEGER NOT NULL,
            digest TEXT,
            PRIMARY KEY (order_id, revision)
        )
    """)


def _read(db, order_id):
    row = db.execute("""
        SELECT status, owner, submission, digest
        FROM review_orders WHERE order_id = ?
    """, (order_id,)).fetchone()
    if row is None:
        return {"ok": False}
    events = db.execute("""
        SELECT operation FROM review_events WHERE order_id = ? ORDER BY revision
    """, (order_id,))
    return dict(ok=True, status=row[0], owner=row[1], submission=row[2],
                digest=row[3], events=[event[0] for event in events])


def _transition(db, op, args):
    if op == "create":
        _create_tables(db)
        statement = """
            INSERT INTO review_orders (order_id, status) VALUES (:order_id, 'open')
            ON CONFLICT (order_id) DO NOTHING
        """
    elif op == "claim":
        statement = """
            UPDATE review_orders
            SET status = 'in_progress', owner = :actor, revision = revision + 1
            WHERE order_id = :order_id AND status = 'open' AND owner IS NULL
        """
    elif op == "submit":
        statement = """
            UPDATE review_orders
            SET status = 'in_review', submission = submission + 1,
                digest = :digest, revision = revision + 1
            WHERE order_id = :order_id AND status = 'in_progress' AND owner = :actor
        """
    else:
        args["next_status"] = "open" if op == "reject" else "released"
        statement = """
            UPDATE review_orders
            SET status = :next_status, revision = revision + 1,
                owner = CASE WHEN :next_status = 'open' THEN NULL ELSE owner END
            WHERE order_id = :order_id AND status = 'in_review' AND submission = :submission
        """
    if db.execute(statement, args).rowcount != 1:
        return {"ok": False}
    db.execute("""
        INSERT INTO review_events (order_id, revision, operation, actor, submission, digest)
        SELECT order_id, revision, :op, :actor, submission, digest
        FROM review_orders WHERE order_id = :order_id
    """, args)
    return {"ok": True}


_ROLES = {
    "create": "reviewer",
    "claim": "agent",
    "submit": "agent",
    "reject": "reviewer",
    "approve": "reviewer",
}


def solve(request):
    if not isinstance(request, dict):
        return {"ok": False}
    op = request.get("op")
    order_id = request.get("order")
    if not isinstance(op, str) or type(order_id) not in (str, int):
        return {"ok": False}
    args = {"order_id": order_id, "op": op, "actor": request.get("actor")}
    if op != "read":
        if op not in _ROLES or request.get("role") != _ROLES[op]:
            return {"ok": False}
        if not isinstance(args["actor"], str) or not args["actor"]:
            return {"ok": False}
    if op == "submit":
        artifact = request.get("artifact")
        if not isinstance(artifact, str) or not artifact.isascii():
            return {"ok": False}
        args["digest"] = hashlib.sha256(artifact.encode("ascii")).hexdigest()
    if op in ("approve", "reject"):
        number = request.get("submission")
        if type(number) is not int or number < 1:
            return {"ok": False}
        args["submission"] = number

    try:
        with closing(sqlite3.connect(request["db"], timeout=30, isolation_level=None)) as db:
            with db:
                # A read sees the state and its history from one snapshot.
                db.execute("BEGIN" if op == "read" else "BEGIN IMMEDIATE")
                if op == "read":
                    return _read(db, order_id)
                return _transition(db, op, args)
    except (sqlite3.Error, KeyError, TypeError, ValueError, OverflowError):
        # The transaction context rolls back a failed event insert or commit.
        return {"ok": False}
