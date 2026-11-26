"""Private Vercel Blob persistence for a small shared lab using conditional SQLite snapshots."""

from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx

from .hosted_storage import HostedStorageError, _RequestStore


MAX_BYTES = 8 * 1024 * 1024
MAX_ATTEMPTS = 4
_WRITE_URL = "https://vercel.com/api/blob/"
_DEFAULT_PATH = "labfactory/lab.sqlite3"
_PRIVATE_SUFFIX = ".private.blob.vercel-storage.com"


def _location(token):
    token_match = re.fullmatch(r"vercel_blob_rw_([A-Za-z0-9-]+)_\S+", token)
    configured = os.environ.get("LABFACTORY_BLOB_URL")
    if not configured:
        if not token_match:
            raise HostedStorageError("Set LABFACTORY_BLOB_URL to the private snapshot URL")
        configured = f"https://{token_match[1].lower()}{_PRIVATE_SUFFIX}/{_DEFAULT_PATH}"
    try:
        parts = urlsplit(configured)
        hostname = parts.hostname or ""
    except ValueError:
        raise HostedStorageError("Invalid private Vercel Blob URL") from None
    if (parts.scheme != "https" or parts.netloc.lower() != hostname
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.private\.blob\.vercel-storage\.com", hostname)
            or parts.query or parts.fragment or not parts.path.startswith("/")
            or not all(re.fullmatch(r"[A-Za-z0-9._-]+", segment) and segment not in (".", "..")
                       for segment in parts.path[1:].split("/"))):
        raise HostedStorageError("Invalid private Vercel Blob URL")
    if token_match and hostname != token_match[1].lower() + _PRIVATE_SUFFIX:
        raise HostedStorageError("Private blob and credential must belong to the same store")
    return configured, parts.path[1:]


def _read(client, url):
    # Vercel's private delivery endpoint bypasses its CDN cache for cache=0.
    # Compressed delivery can weaken the ETag. Request the original object bytes
    # so the ETag identifies the same representation used for conditional PUT.
    with client.stream("GET", url, params={"cache": "0"}, headers={"Accept-Encoding": "identity"}) as response:
        if response.status_code == 404:
            return None, None
        if response.status_code != 200:
            raise HostedStorageError("Could not read the private lab snapshot")
        etag = response.headers.get("etag")
        if not etag or etag == "*" or etag.startswith("W/"):
            raise HostedStorageError("Private lab snapshot has no strong ETag")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise HostedStorageError("Private lab snapshot exceeds the 8 MiB limit")
        data = bytearray()
        for chunk in response.iter_bytes(65536):
            if len(data) + len(chunk) > MAX_BYTES:
                raise HostedStorageError("Private lab snapshot exceeds the 8 MiB limit")
            data.extend(chunk)
        if not data.startswith(b"SQLite format 3\x00"):
            raise HostedStorageError("Invalid SQLite snapshot in the private blob")
        return bytes(data), etag


def _mutate(snapshot, operation, write):
    # A request-private temporary file also works with Python builds that omit
    # sqlite3_serialize. The durable copy is the conditionally written blob.
    with TemporaryDirectory() as directory:
        path = Path(directory) / "lab.sqlite3"
        if snapshot is not None:
            path.write_bytes(snapshot)
        with closing(sqlite3.connect(path, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count = {MAX_BYTES // page_size}")
            store = _RequestStore(db)
            # For a missing blob the initial schema alone is not a requested change.
            before = snapshot if snapshot is not None or not write else path.read_bytes()
            result = store.run(operation, write)
        if not write:
            return result, None
        if path.stat().st_size > MAX_BYTES:
            raise HostedStorageError("Private lab snapshot exceeds the 8 MiB limit")
        updated = path.read_bytes()
        return result, updated if updated != before else None


def _write(client, pathname, etag, snapshot):
    # The Blob API uses its own conditional header (not HTTP If-Match).
    headers = {
        "x-api-version": "13",
        "x-vercel-blob-access": "private",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1" if etag else "0",
        "x-content-type": "application/octet-stream",
    }
    if etag:
        headers["x-if-match"] = etag
    response = client.put(_WRITE_URL, params={"pathname": pathname}, headers=headers, content=snapshot)
    if response.is_success:
        return True
    if response.status_code == 412:
        return False
    if response.status_code in (400, 409):
        try:
            error = response.json()["error"]
            code = error["code"]
            message = error.get("message", "").lower()
        except (TypeError, KeyError, ValueError, AttributeError):
            code = message = ""
        if code == "precondition_failed" or (not etag and "already exists" in message):
            return False
    raise HostedStorageError("Lab snapshot write could not be confirmed. Check current work order history.")


def run_blob_store(operation, *, write=False):
    """Run one database-only callback, replaying only after a definitive write conflict."""
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise HostedStorageError("Set BLOB_READ_WRITE_TOKEN for the private lab store")
    url, pathname = _location(token)
    try:
        with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=8, follow_redirects=False) as client:
            for _ in range(MAX_ATTEMPTS):
                snapshot, etag = _read(client, url)
                result, updated = _mutate(snapshot, operation, write)
                if updated is None or _write(client, pathname, etag, updated):
                    return result
    except httpx.HTTPError:
        # An interrupted PUT may have committed. Do not replay it.
        raise HostedStorageError("Lab storage request interrupted. Check current work order history.") from None
    except sqlite3.Error as exc:
        if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
            raise HostedStorageError("Private lab snapshot exceeds the 8 MiB limit") from None
        raise HostedStorageError("Could not process the private lab snapshot") from None
    raise HostedStorageError("Lab history changed during each write attempt. Retry the operation.")
