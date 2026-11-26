"""A local, size-capped SQLite snapshot for immutable experiment records."""

import fcntl
import hashlib
import os
import shutil
import sqlite3
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory


MAX_BYTES = 8 * 1024 * 1024


@contextmanager
def _writer_lock(root):
    # A separate, stable inode protects the whole read-modify-replace operation.
    with (root / "writer.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _materialize(snapshot, work):
    try:
        source = snapshot.open("rb")
    except FileNotFoundError:
        return False
    # An open descriptor keeps this version stable across a concurrent rename.
    with source:
        if os.fstat(source.fileno()).st_size > MAX_BYTES:
            raise ValueError("oversized snapshot")
        if source.read(16) != b"SQLite format 3\x00":
            raise ValueError("invalid snapshot header")
        source.seek(0)
        with work.open("wb") as target:
            shutil.copyfileobj(source, target)
    return True


def _operate(db, op, key, payload):
    if op == "list":
        rows = db.execute("SELECT key FROM records ORDER BY key")
        return {"ok": True, "keys": [row[0] for row in rows]}, False

    row = db.execute(
        "SELECT payload, digest FROM records WHERE key = ?", (key,)
    ).fetchone()
    if row is not None:
        stored, digest = row
        if hashlib.sha256(stored).hexdigest() != digest:
            return {"ok": False}, False
        if op == "get":
            return {"ok": True, "digest": digest, "payload": stored}, False
        if payload == stored:
            return {"ok": True, "digest": digest}, False
        return {"ok": False}, False

    if op == "get":
        return {"ok": False}, False
    digest = hashlib.sha256(payload).hexdigest()
    db.execute("INSERT INTO records VALUES (?, ?, ?)", (key, payload, digest))
    db.commit()
    return {"ok": True, "digest": digest}, True


def _request(root, op, key, payload):
    snapshot = root / "snapshot.sqlite3"
    guard = _writer_lock(root) if op == "put" else nullcontext()
    with guard, TemporaryDirectory(dir=root) as directory:
        work = Path(directory) / "work.sqlite3"
        exists = _materialize(snapshot, work)
        if not exists and op != "put":
            return {"ok": True, "keys": []} if op == "list" else {"ok": False}

        with closing(sqlite3.connect(work)) as db:
            db.execute("PRAGMA temp_store = MEMORY")
            db.execute("PRAGMA journal_mode = MEMORY")
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count = {MAX_BYTES // page_size}")
            if not exists:
                db.execute(
                    "CREATE TABLE records (key TEXT PRIMARY KEY, payload BLOB NOT NULL,"
                    " digest TEXT NOT NULL) WITHOUT ROWID"
                )
            result, changed = _operate(db, op, key, payload)

        if changed:
            with work.open("rb") as staged:
                if os.fstat(staged.fileno()).st_size > MAX_BYTES:
                    return {"ok": False}
                os.fsync(staged.fileno())
            os.replace(work, snapshot)
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return result


def solve(request):
    op = request.get("op")
    key = request.get("key")
    payload = request.get("payload")
    if op not in ("put", "get", "list"):
        return {"ok": False}
    if op != "list" and not (isinstance(key, str) and key and key.isascii()):
        return {"ok": False}
    if op == "put" and (not isinstance(payload, bytes) or len(payload) > MAX_BYTES):
        return {"ok": False}
    try:
        root = Path(request["root"])
        root.mkdir(parents=True, exist_ok=True)
        return _request(root, op, key, payload)
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return {"ok": False}
