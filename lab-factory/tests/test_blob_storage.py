from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import threading

import httpx
import pytest

from labfactory import blob_storage
from labfactory.blob_storage import HostedStorageError, run_blob_store
from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.workorders import WorkOrders, WorkOrderError


TOKEN = "vercel_blob_rw_UnitTestStore_disposable"
HOST = "unitteststore.private.blob.vercel-storage.com"


class PrivateBlob:
    def __init__(self):
        self.data = None
        self.etag = None
        self.mutex = threading.Lock()
        self.race = None
        self.interrupt_after_upload = False
        self.fail_conflicts = False
        self.attempts = 0
        self.published = 0

    def handle(self, request):
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.method == "GET":
            assert request.url.host == HOST and dict(request.url.params) == {"cache": "0"}
            assert request.url.path == "/labfactory/lab.sqlite3"
            assert request.headers["accept-encoding"] == "identity"
            with self.mutex:
                data, tag, barrier = self.data, self.etag, self.race
            if barrier:
                barrier.wait(timeout=3)
                with self.mutex:
                    if self.race is barrier:
                        self.race = None
            if data is None:
                return httpx.Response(404)
            return httpx.Response(200, content=data, headers={"ETag": tag} if tag else {})

        assert request.method == "PUT" and request.url.host == "vercel.com"
        assert request.url.params["pathname"] == "labfactory/lab.sqlite3"
        assert request.headers["x-api-version"] == "13"
        assert request.headers["x-vercel-blob-access"] == "private"
        assert request.headers["x-add-random-suffix"] == "0"
        expected = request.headers.get("x-if-match")
        assert request.headers["x-allow-overwrite"] == ("1" if expected else "0")
        with self.mutex:
            self.attempts += 1
            if self.fail_conflicts or (expected and expected != self.etag):
                return httpx.Response(412)
            if self.data is not None and not expected:
                return httpx.Response(400, json={"error": {"code": "bad_request", "message": "This blob already exists"}})
            self.data = request.content
            self.etag = '"' + sha256(self.data).hexdigest() + '"'
            self.published += 1
            if self.interrupt_after_upload:
                raise httpx.ReadTimeout("simulated lost response")
        return httpx.Response(200, json={})


@pytest.fixture
def blob(monkeypatch):
    backend = PrivateBlob()
    real_client = httpx.Client
    def client(**options):
        return real_client(transport=httpx.MockTransport(backend.handle), **options)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", TOKEN)
    monkeypatch.delenv("LABFACTORY_BLOB_URL", raising=False)
    monkeypatch.setattr(blob_storage.httpx, "Client", client)
    return backend


def test_atomic_creation_and_concurrent_claim(blob, uvvis_lab_dict, b12_experiment_dict):
    assert run_blob_store(lambda store: WorkOrders(store).list()) == []
    assert blob.attempts == 0

    def seed(store):
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        experiment = experiment_from_dict(b12_experiment_dict)
        store.put_experiment(experiment)
        return WorkOrders(store).create(experiment.id, "run_plan", "Read absorbance").id

    # Both requests see a missing key. Losing initial PUT must rerun and append
    # its independent new work order against the winner's committed history.
    with ThreadPoolExecutor(max_workers=2) as pool:
        blob.race = threading.Barrier(2)
        records = list(pool.map(lambda _: run_blob_store(seed, write=True), range(2)))
        assert sorted(records) == ["WO-1", "WO-2"] and blob.published == 2
        def claim(worker):
            try:
                return run_blob_store(lambda store: WorkOrders(store).claim("WO-1", worker), write=True).worker
            except WorkOrderError:
                return None

        blob.race = threading.Barrier(2)
        outcomes = list(pool.map(claim, ("worker-a", "worker-b")))
    winners = [name for name in outcomes if name]
    assert len(winners) == 1
    claim_events = run_blob_store(lambda store: [
        row[0] for row in store.connection.execute("SELECT actor FROM events WHERE event = 'claimed'")
    ])
    assert claim_events == winners
    assert blob.attempts == 5 and blob.published == 3


def test_unknown_outcome_is_never_replayed(blob, uvvis_lab_dict):
    blob.interrupt_after_upload = True
    callback_calls = []
    def save(store):
        callback_calls.append(True)
        return store.put_lab(lab_from_dict(uvvis_lab_dict))

    with pytest.raises(HostedStorageError, match="Check current work order history"):
        run_blob_store(save, write=True)
    assert len(callback_calls) == 1 and blob.attempts == 1
    assert run_blob_store(lambda store: store.get_lab(uvvis_lab_dict["id"])[1].number) == 1


def test_failed_callback_rolls_back_and_retries_are_bounded(blob, uvvis_lab_dict):
    lab = lab_from_dict(uvvis_lab_dict)
    def interrupted(store):
        store.put_lab(lab)
        raise RuntimeError("caller failed")
    with pytest.raises(RuntimeError, match="caller failed"):
        run_blob_store(interrupted, write=True)
    assert not blob.attempts
    blob.fail_conflicts = True
    with pytest.raises(HostedStorageError, match="changed"):
        run_blob_store(lambda store: store.put_lab(lab), write=True)
    assert blob.attempts == blob_storage.MAX_ATTEMPTS


def test_invalid_or_oversize_snapshot_fails_closed(blob):
    for body, etag, message in [
        (b"", '"abc"', "Invalid SQLite"),
        (b"unexpected", None, "strong ETag"),
        (b"unexpected", "*", "strong ETag"),
        (b"x" * (blob_storage.MAX_BYTES + 1), '"abc"', "8 MiB"),
    ]:
        blob.data, blob.etag = body, etag
        with pytest.raises(HostedStorageError, match=message):
            run_blob_store(lambda store: None, write=True)
    assert not blob.attempts


def test_output_size_is_bounded(blob):
    def oversized(store):
        with store.transaction() as db:
            db.execute("CREATE TABLE extra (v BLOB)")
            db.execute("INSERT INTO extra VALUES (zeroblob(?))", (blob_storage.MAX_BYTES,))
    with pytest.raises(HostedStorageError, match="8 MiB"):
        run_blob_store(oversized, write=True)
    assert not blob.attempts


def test_configured_path_requires_private_store_origin(blob, monkeypatch):
    for url in (
        "https://elsewhere.test/lab.sqlite", f"http://{HOST}/lab.sqlite",
        "https://other.private.blob.vercel-storage.com/x", f"https://test@{HOST}/x",
        f"https://{HOST}/other/../lab", f"https://{HOST}/lab?cache=1", "https://[broken",
    ):
        monkeypatch.setenv("LABFACTORY_BLOB_URL", url)
        with pytest.raises(HostedStorageError):
            run_blob_store(lambda store: None)
    monkeypatch.setenv("LABFACTORY_BLOB_URL", f"https://{HOST}/approved/custom.sqlite")
    assert blob_storage._location(TOKEN)[1] == "approved/custom.sqlite"
