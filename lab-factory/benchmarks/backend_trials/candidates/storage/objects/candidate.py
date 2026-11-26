"""Store immutable payloads by digest and publish their logical keys in SQLite."""

import hashlib
import os
import sqlite3
import tempfile
from contextlib import ExitStack, closing
from pathlib import Path


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _lookup(db, key):
    row = db.execute("SELECT digest FROM records WHERE key = ?", (key,)).fetchone()
    return row[0] if row is not None else None


def _verify_object(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    if checksum.hexdigest() != path.name:
        raise ValueError("Object failed its digest check")


def _put(db, objects, key, payload):
    digest = hashlib.sha256(payload).hexdigest()
    existing = _lookup(db, key)
    if existing is not None and existing != digest:
        return {"ok": False}

    try:
        objects.mkdir()
    except FileExistsError:
        if not objects.is_dir():
            raise
    else:
        _sync_directory(objects.parent)

    target = objects / digest
    if target.is_symlink():
        raise ValueError("Unexpected object symlink")
    with ExitStack() as cleanup:
        staged = None
        if target.exists():
            _verify_object(target)
            if existing == digest:
                return {"ok": True, "digest": digest}
        else:
            # Do the payload I/O before taking the metadata writer lock.
            staged = cleanup.enter_context(tempfile.NamedTemporaryFile(dir=objects))
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())

        with db:
            db.execute("BEGIN IMMEDIATE")
            winner = _lookup(db, key)
            if winner is not None and winner != digest:
                return {"ok": False}
            if staged is not None:
                try:
                    os.link(staged.name, target)
                except FileExistsError:
                    _verify_object(target)
            # A durable key must always refer to an already durable object.
            _sync_directory(objects)
            if winner is None:
                db.execute("INSERT INTO records(key, digest) VALUES (?, ?)", (key, digest))
    return {"ok": True, "digest": digest}


def solve(request):
    try:
        op = request["op"]
        if op not in ("get", "put", "list") or not request["root"]:
            return {"ok": False}
        if op != "list":
            key = request["key"]
            if not isinstance(key, str) or not key or not key.isascii():
                return {"ok": False}
        if op == "put" and not isinstance(request["payload"], bytes):
            return {"ok": False}

        root = Path(request["root"])
        root.mkdir(parents=True, exist_ok=True)
        objects = root / "objects"
        index = root / "index.sqlite3"
        if objects.is_symlink() or any(
            (root / (index.name + suffix)).is_symlink()
            for suffix in ("", "-journal", "-wal", "-shm")
        ):
            return {"ok": False}

        with closing(sqlite3.connect(index, timeout=30)) as db:
            db.execute("PRAGMA synchronous = FULL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(key TEXT PRIMARY KEY, digest TEXT NOT NULL) WITHOUT ROWID"
            )
            if op == "put":
                return _put(db, objects, key, request["payload"])
            if op == "list":
                rows = db.execute("SELECT key FROM records ORDER BY key")
                return {"ok": True, "keys": [row[0] for row in rows]}

            digest = _lookup(db, key)
            if not isinstance(digest, str) or len(digest) != 64 or any(
                c not in "0123456789abcdef" for c in digest
            ):
                return {"ok": False}
            target = objects / digest
            if target.is_symlink():
                return {"ok": False}
            payload = target.read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest:
                return {"ok": False}
            return {"ok": True, "digest": digest, "payload": payload}
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return {"ok": False}
