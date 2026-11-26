"""A review round consists of one claim, one submission, and one decision."""

import hashlib
import sqlite3
from contextlib import closing


_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS review_orders (
    order_id PRIMARY KEY NOT NULL,
    creator TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_claims (
    order_id NOT NULL REFERENCES review_orders,
    round INTEGER NOT NULL CHECK (round >= 1),
    owner TEXT NOT NULL,
    PRIMARY KEY (order_id, round)
);
CREATE TABLE IF NOT EXISTS review_submissions (
    order_id NOT NULL,
    round INTEGER NOT NULL,
    digest TEXT NOT NULL CHECK (length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (order_id, round),
    FOREIGN KEY (order_id, round) REFERENCES review_claims
);
CREATE TABLE IF NOT EXISTS review_decisions (
    order_id NOT NULL,
    round INTEGER NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('reject', 'approve')),
    PRIMARY KEY (order_id, round),
    FOREIGN KEY (order_id, round) REFERENCES review_submissions
);
CREATE TRIGGER IF NOT EXISTS review_require_rejection
BEFORE INSERT ON review_claims
WHEN NEW.round > 1 AND NOT EXISTS (
    SELECT 1 FROM review_decisions
    WHERE order_id = NEW.order_id AND round = NEW.round - 1 AND decision = 'reject'
)
BEGIN
    SELECT RAISE(ABORT, 'previous round must be rejected before another claim');
END;
CREATE VIEW IF NOT EXISTS review_events AS
    SELECT order_id, 0 AS round, 0 AS step, 'create' AS event, creator AS actor,
           NULL AS digest FROM review_orders
    UNION ALL
    SELECT order_id, round, 1, 'claim', owner, NULL FROM review_claims
    UNION ALL
    SELECT order_id, round, 2, 'submit', owner, digest
    FROM review_submissions JOIN review_claims USING (order_id, round)
    UNION ALL
    SELECT order_id, round, 3, decision, reviewer, digest
    FROM review_decisions JOIN review_submissions USING (order_id, round);
COMMIT;
"""

# A decision can target any supplied number. Every earlier submission already
# has a decision (required for a later claim), so its primary key bars a replay.
_DECIDE = """
    INSERT INTO review_decisions (order_id, round, reviewer, decision)
    SELECT :order, :submission, :actor, :op WHERE :role = 'reviewer'
"""
_WRITES = {
    "create": """
        INSERT INTO review_orders (order_id, creator)
        SELECT :order, :actor WHERE :role = 'reviewer'
    """,
    "claim": """
        INSERT INTO review_claims (order_id, round, owner)
        SELECT :order, (SELECT COALESCE(MAX(round), 0) + 1 FROM review_claims
                        WHERE order_id = :order), :actor
        WHERE :role = 'agent'
    """,
    "submit": """
        INSERT INTO review_submissions (order_id, round, digest)
        SELECT order_id, round, :digest FROM review_claims
        WHERE order_id = :order AND owner = :actor AND :role = 'agent'
        ORDER BY round DESC LIMIT 1
    """,
    "approve": _DECIDE,
    "reject": _DECIDE,
}


def _read(connection, order):
    rows = connection.execute(
        "SELECT round, event, actor, digest FROM review_events "
        "WHERE order_id = ? ORDER BY round, step", (order,)
    )
    events = []
    owner = digest = None
    submission = 0
    for number, event, actor, artifact_digest in rows:
        events.append(event)
        if event == "claim":
            owner = actor
        elif event == "reject":
            owner = None
        elif event == "submit":
            submission, digest = number, artifact_digest
    if not events:
        return {"ok": False}
    statuses = {"create": "open", "claim": "in_progress", "submit": "in_review",
                "reject": "open", "approve": "released"}
    return {"ok": True, "events": events, "status": statuses[events[-1]],
            "owner": owner, "submission": submission, "digest": digest}


def solve(request):
    """Apply one guarded insert, or read the ordered history in one snapshot."""
    try:
        op = request["op"]
        if op not in _WRITES and op != "read":
            return {"ok": False}
        if request["role"] not in ("reviewer", "agent"):
            return {"ok": False}
        if not isinstance(request["actor"], str) or not request["actor"]:
            return {"ok": False}
        if type(request["order"]) not in (str, int):
            return {"ok": False}
        params = dict(request)
        if op == "submit":
            artifact = params["artifact"]
            if not isinstance(artifact, str):
                return {"ok": False}
            params["digest"] = hashlib.sha256(artifact.encode("ascii")).hexdigest()
        if op in ("approve", "reject") and type(params["submission"]) is not int:
            return {"ok": False}
        with closing(sqlite3.connect(request["db"], timeout=10, isolation_level=None)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = 'review_events'"
            ).fetchone():
                db.executescript(_SCHEMA)
            if op == "read":
                return _read(db, params["order"])
            return {"ok": db.execute(_WRITES[op], params).rowcount == 1}
    except (sqlite3.Error, KeyError, TypeError, ValueError, OverflowError):
        return {"ok": False}
