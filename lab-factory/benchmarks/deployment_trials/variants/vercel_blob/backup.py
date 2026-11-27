"""Back up and restore the pinned layout through the trial sidecar's Blob operations."""

from collections import Counter
from contextlib import closing
from hashlib import sha256
import re
import sqlite3

import httpx


SNAPSHOT = "labfactory/lab.sqlite3"


def digest(data):
    return sha256(data).hexdigest()


def get_object(client, key):
    response = client.get("/" + key, params={"cache": "0"}, headers={"Accept-Encoding": "identity"})
    response.raise_for_status()
    return response.content


def put_new_object(client, key, data):
    headers = {"x-api-version": "13", "x-vercel-blob-access": "private", "x-content-type": "application/octet-stream",
               "x-add-random-suffix": "0", "x-allow-overwrite": "0"}
    client.put("/api/blob/", params={"pathname": key}, headers=headers, content=data).raise_for_status()


def storage_client(port, token):
    return httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": "Bearer " + token},
                        timeout=8, follow_redirects=False, trust_env=False)


def make_backup(directory, port, token):
    directory.mkdir(mode=0o700)
    (directory / "uploads").mkdir(mode=0o700)
    with storage_client(port, token) as client:
        snapshot = get_object(client, SNAPSHOT)
        db_path = directory / "lab.sqlite3"
        db_path.write_bytes(snapshot)
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Snapshot failed SQLite checks")
            rows = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in (
                "records", "work_orders", "submissions", "events", "tabular_files", "tabular_intakes",
                "tabular_controls", "tabular_reports", "tabular_runs")}
            external = db.execute("SELECT digest FROM tabular_files WHERE local_text IS NULL ORDER BY digest").fetchall()
            receipts = dict(Counter(row[0] for row in db.execute("SELECT json_extract(receipt,'$.status') FROM tabular_runs")))
            uploaded = {}
            for key, in external:
                if not re.fullmatch(r"[a-f0-9]{64}", key):
                    raise ValueError("Malformed upload reference in snapshot")
                data = get_object(client, "labfactory/uploads/" + key)
                if digest(data) != key:
                    raise ValueError("Original failed content digest check")
                (directory / "uploads" / key).write_bytes(data)
                uploaded[key] = len(data)
    return {"snapshot_sha256": digest(snapshot), "snapshot_bytes": len(snapshot), "sqlite_integrity": "ok",
            "foreign_key_violations": 0, "table_rows": rows, "receipt_statuses": receipts,
            "external_originals_sha256_to_bytes": uploaded, "originals_bytes": sum(uploaded.values())}


def restore_backup(directory, manifest, port, token):
    with storage_client(port, token) as client:
        # Install immutable dependencies before publishing the snapshot that refers to them.
        for key, length in manifest["external_originals_sha256_to_bytes"].items():
            data = (directory / "uploads" / key).read_bytes()
            if digest(data) != key or len(data) != length:
                raise ValueError("Backup upload failed digest verification")
            put_new_object(client, "labfactory/uploads/" + key, data)
        data = (directory / "lab.sqlite3").read_bytes()
        if digest(data) != manifest["snapshot_sha256"]:
            raise ValueError("Backup database failed digest verification")
        put_new_object(client, SNAPSHOT, data)
        if digest(get_object(client, SNAPSHOT)) != manifest["snapshot_sha256"]:
            raise ValueError("Restored database failed readback")
