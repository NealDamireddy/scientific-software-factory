"""Immutable artifact records and their bytes in a local SQLite WAL database."""

import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path


def _access(db, op, key, payload, digest):
    if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
        return {"ok": False, "error": "wal_unavailable"}
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute(
        "CREATE TABLE IF NOT EXISTS artifacts ("
        "key TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, payload BLOB NOT NULL)"
    )

    if op == "list":
        keys = [row[0] for row in db.execute("SELECT key FROM artifacts ORDER BY key")]
        return {"ok": True, "keys": keys}

    if op == "get":
        row = db.execute(
            "SELECT digest, payload FROM artifacts WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "missing"}
        stored_digest, stored_payload = row
        if (
            not isinstance(stored_payload, bytes)
            or hashlib.sha256(stored_payload).hexdigest() != stored_digest
        ):
            return {"ok": False, "error": "integrity"}
        return {"ok": True, "digest": stored_digest, "payload": stored_payload}

    with db:
        inserted = db.execute(
            "INSERT INTO artifacts (key, digest, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (key, digest, payload),
        ).rowcount
        if not inserted:
            # Compare the bytes too, so idempotence requires exact equality.
            matches = db.execute(
                "SELECT digest = ? AND payload = ? FROM artifacts WHERE key = ?",
                (digest, payload, key),
            ).fetchone()[0]
            if not matches:
                return {"ok": False, "error": "conflict"}
    return {"ok": True, "digest": digest}


def solve(request):
    op = request.get("op")
    key = request.get("key")
    payload = request.get("payload")
    if op not in ("get", "put", "list"):
        return {"ok": False, "error": "unknown_operation"}
    if op != "list" and not (isinstance(key, str) and key and key.isascii()):
        return {"ok": False, "error": "invalid_key"}
    if op == "put" and not isinstance(payload, bytes):
        return {"ok": False, "error": "invalid_payload"}
    digest = hashlib.sha256(payload).hexdigest() if op == "put" else None

    try:
        root = Path(request["root"])
        root.mkdir(parents=True, exist_ok=True)
        path = root / "artifacts.sqlite3"
    except (OSError, TypeError, KeyError, ValueError):
        return {"ok": False, "error": "invalid_root"}

    deadline = time.monotonic() + 15
    while True:
        try:
            with closing(sqlite3.connect(path, timeout=1, isolation_level="IMMEDIATE")) as db:
                return _access(db, op, key, payload, digest)
        except sqlite3.Error as exc:
            # Concurrent first open can return BUSY during the switch to WAL.
            code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
            if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return {"ok": False, "error": "database"}
            if time.monotonic() >= deadline:
                return {"ok": False, "error": "busy"}
            time.sleep(0.025)
