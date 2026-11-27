"""Inspect, snapshot and restore the Lab Factory SQLite volume. Requires SQLite 3.37+."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def encode(value):
    # SQLite blobs have a distinct representation from strings and numbers.
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      default=lambda blob: {"blob_hex": blob.hex()}).encode() + b"\n"


def inspect(database):
    digest = hashlib.sha256()
    counts, hashes = {}, {}
    with closing(readonly(database)) as connection:
        connection.execute("BEGIN")  # Use one snapshot across all integrity and data queries.
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("integrity_check_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("foreign_key_check_failed")
        for pragma in ("application_id", "user_version"):
            digest.update(encode([pragma, connection.execute(f"PRAGMA {pragma}").fetchone()[0]]))
        for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"):
            digest.update(encode(row))

        tables = connection.execute(
            "SELECT name,wr FROM pragma_table_list WHERE schema='main' AND type='table' "
            "AND name<>'sqlite_schema' ORDER BY name"
        )
        for name, without_rowid in tables:
            table = identifier(name)
            if without_rowid:
                keys = connection.execute("SELECT name FROM pragma_table_info(?) WHERE pk>0 ORDER BY pk", (name,))
                columns = "*"
                order = ",".join(identifier(key[0]) for key in keys)
            else:
                # Event rowids are consumed as history cursors by this backend.
                columns, order = "rowid,*", "rowid"
            count = 0
            table_digest = hashlib.sha256()
            for row in connection.execute(f"SELECT {columns} FROM {table} ORDER BY {order}"):
                table_digest.update(encode(row))
                count += 1
            counts[name], hashes[name] = count, table_digest.hexdigest()
            digest.update(encode([name, count, hashes[name]]))
    return {"integrity_check": "ok", "foreign_key_check": "ok", "table_counts": counts,
            "table_sha256": hashes, "logical_sha256": digest.hexdigest()}


def copy_snapshot(source, destination):
    sidecars = [Path(str(destination) + suffix) for suffix in ("-journal", "-shm", "-wal")]
    if any(os.path.lexists(path) for path in [destination, *sidecars]):
        raise FileExistsError
    with tempfile.TemporaryDirectory(prefix=".labfactory-snapshot-", dir=destination.parent) as temp:
        staged = Path(temp) / "snapshot.sqlite3"
        staged.touch(mode=0o600, exist_ok=False)
        deadline = time.monotonic() + 60

        def check_deadline(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError

        with closing(readonly(source)) as origin, closing(sqlite3.connect(staged)) as target:
            origin.backup(target, pages=256, progress=check_deadline, sleep=0.05)
            target.execute("PRAGMA journal_mode=DELETE")
        result = inspect(staged)
        # Publish the validated single file without replacing a concurrent writer's database.
        with staged.open("rb") as verified:
            os.fsync(verified.fileno())
        os.link(staged, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("inspect").add_argument("source", type=Path)
    for action in ("backup", "restore"):
        command = commands.add_parser(action)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path, help="New filename in an existing directory")
    args = parser.parse_args()
    started = time.monotonic()
    try:
        if args.operation == "inspect":
            result = inspect(args.source)
        else:
            result = copy_snapshot(args.source, args.destination)
    except (OSError, sqlite3.Error, ValueError) as exc:
        # SQL diagnostics can include record contents or sensitive filesystem paths.
        print(json.dumps({"operation": args.operation, "error": type(exc).__name__}), file=sys.stderr)
        return 1
    result.update(operation=args.operation, duration_ms=round((time.monotonic() - started) * 1000, 3))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
