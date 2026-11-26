"""Content-addressed private originals. Hosted files live beside the lab's SQLite blob."""

from hashlib import sha256
import os
from urllib.parse import urlsplit

import httpx

from .blob_storage import _location, _write
from .hosted_storage import HostedStorageError


MAX_FILE_BYTES = 128 * 1024


def digest(content):
    return sha256(content.encode("utf-8")).hexdigest()


def _remote(token, key):
    url, snapshot = _location(token)
    path = "/".join(part for part in (snapshot.rpartition("/")[0], "uploads", key) if part)
    return urlsplit(url)._replace(path="/" + path).geturl(), path


def _download(client, url, key):
    with client.stream("GET", url, params={"cache": "0"}, headers={"Accept-Encoding": "identity"}) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes(65536):
            if len(data) + len(chunk) > MAX_FILE_BYTES:
                raise HostedStorageError("Pinned upload exceeds the original file size limit")
            data.extend(chunk)
    if sha256(data).hexdigest() != key:
        raise HostedStorageError("Pinned upload digest does not match")
    return data.decode("utf-8")


def save(db, content):
    key = digest(content)
    if db.execute("SELECT 1 FROM tabular_files WHERE digest=?", (key,)).fetchone():
        return key
    token = os.getenv("BLOB_READ_WRITE_TOKEN") if not os.getenv("LABFACTORY_LOCAL_DB") else None
    if token:
        url, path = _remote(token, key)
        try:
            with httpx.Client(headers={"Authorization": "Bearer " + token}, timeout=12, follow_redirects=False) as client:
                # Snapshot CAS retries or a lost PUT acknowledgement may find an existing file.
                # Verify the content on conflicts before we commit any reference to it.
                if not _write(client, path, None, content.encode("utf-8")):
                    _download(client, url, key)
        except (httpx.HTTPError, UnicodeError):
            raise HostedStorageError("The private upload could not be saved.") from None
    db.execute("INSERT INTO tabular_files(digest, local_text) VALUES (?,?)", (key, None if token else content))
    return key


def load(db, key):
    row = db.execute("SELECT local_text FROM tabular_files WHERE digest=?", (key,)).fetchone()
    if row is None:
        raise HostedStorageError("Missing pinned upload")
    content = row["local_text"]
    if content is None:
        token = os.getenv("BLOB_READ_WRITE_TOKEN")
        if not token:
            raise HostedStorageError("Missing private upload credential")
        url, _ = _remote(token, key)
        try:
            with httpx.Client(headers={"Authorization": "Bearer " + token}, timeout=12, follow_redirects=False) as client:
                return _download(client, url, key)
        except (httpx.HTTPError, UnicodeError):
            raise HostedStorageError("The pinned private upload could not be read.") from None
    if digest(content) != key:
        raise HostedStorageError("The pinned upload digest does not match")
    return content
