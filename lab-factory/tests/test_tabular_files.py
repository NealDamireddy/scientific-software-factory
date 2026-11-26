from hashlib import sha256

import httpx
import pytest

from labfactory import tabular_files as files
from labfactory.hosted_storage import HostedStorageError


@pytest.fixture
def private_blobs(monkeypatch):
    blobs = {}
    requests = []
    token = "vercel_blob_rw_UnitTestStore_disposable"
    hostname = "unitteststore.private.blob.vercel-storage.com"

    def dispatch(request):
        requests.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer " + token
        if request.method == "PUT":
            assert request.url.host == "vercel.com" and request.url.path == "/api/blob/"
            key = request.url.params["pathname"]
            assert key.startswith("labfactory/uploads/") and sha256(request.content).hexdigest() == key.rpartition("/")[2]
            assert request.headers["x-vercel-blob-access"] == "private"
            assert request.headers["x-allow-overwrite"] == request.headers["x-add-random-suffix"] == "0"
            if key in blobs:
                return httpx.Response(400, json={"error": {"code": "bad_request", "message": "This blob already exists"}})
            blobs[key] = request.content
            return httpx.Response(200, json={"url": "test"})
        assert request.method == "GET" and request.url.host == hostname
        assert dict(request.url.params) == {"cache": "0"} and request.headers["Accept-Encoding"] == "identity"
        content = blobs.get(request.url.path.lstrip("/"))
        return httpx.Response(404) if content is None else httpx.Response(200, content=content)

    real = httpx.Client
    monkeypatch.setattr(files.httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(dispatch), **kwargs))
    monkeypatch.delenv("LABFACTORY_LOCAL_DB", raising=False)
    monkeypatch.delenv("LABFACTORY_BLOB_URL", raising=False)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", token)
    return blobs, requests


def test_private_originals_are_external_and_content_addressed(store, private_blobs):
    blobs, requests = private_blobs
    with store.transaction() as db:
        content = "Café\r\n20,30\r\n"
        key = files.save(db, content)
        assert files.save(db, content) == key
        assert list(blobs.values()) == [content.encode("utf-8")]
        assert db.execute("SELECT local_text FROM tabular_files WHERE digest=?", (key,)).fetchone()[0] is None
        assert files.load(db, key) == content
        assert [m for m, path in requests] == ["PUT", "GET"]
        # The private object outlives a lost or competing SQLite snapshot update.
        db.execute("DELETE FROM tabular_files")
        assert files.save(db, content) == key
        assert [m for m, path in requests][-2:] == ["PUT", "GET"]
        blobs["labfactory/uploads/" + key] = b"mismatched"
        with pytest.raises(HostedStorageError, match="digest"):
            files.load(db, key)
        db.execute("DELETE FROM tabular_files")
        with pytest.raises(HostedStorageError, match="digest"):
            files.save(db, content)
        assert db.execute("SELECT COUNT(*) FROM tabular_files").fetchone()[0] == 0


def test_local_uploads_hash_originals_and_detect_damage(store, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    with store.transaction() as db:
        key = files.save(db, "file bytes\r\n")
        assert key == sha256(b"file bytes\r\n").hexdigest() and files.load(db, key) == "file bytes\r\n"
        db.execute("UPDATE tabular_files SET local_text='replacement' WHERE digest=?", (key,))
        with pytest.raises(HostedStorageError, match="digest"):
            files.load(db, key)
