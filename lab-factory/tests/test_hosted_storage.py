from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import httpx
import pytest
import turso_serverless as turso

from labfactory.agent import AgentTools
from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.hosted_storage import HostedStorageError, _HttpSession, run_store
from labfactory.store import NotFound
from labfactory.workorders import WorkOrders


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    for name in (
        "VERCEL", "VERCEL_ENV", "LABFACTORY_LOCAL_DB", "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN", "BLOB_READ_WRITE_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_shared_database_fails_closed(tmp_path, monkeypatch):
    with pytest.raises(HostedStorageError, match="TURSO_DATABASE_URL"):
        run_store(lambda store: None)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    with pytest.raises(HostedStorageError, match="TURSO_AUTH_TOKEN"):
        run_store(lambda store: None)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "forbidden.sqlite"))
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(HostedStorageError, match="durable"):
        run_store(lambda store: None)
    assert not list(tmp_path.iterdir())


def test_blob_is_selected_with_its_token_and_explicit_turso_fails_closed(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "test-token")
    monkeypatch.setattr("labfactory.blob_storage.run_blob_store", lambda op, *, write: op(write))
    assert run_store(lambda write: write, write=True)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    with pytest.raises(HostedStorageError, match="TURSO_AUTH_TOKEN"):
        run_store(lambda store: None)


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "history.db"))


def test_callback_rollback_and_read_snapshot(local_store, uvvis_lab_dict):
    lab = lab_from_dict(uvvis_lab_dict)

    def put_then_fail(store):
        store.put_lab(lab)
        raise ValueError("failed callback")

    with pytest.raises(ValueError, match="failed callback"):
        run_store(put_then_fail, write=True)
    with pytest.raises(NotFound):
        run_store(lambda store: store.get_lab(lab.id))

    def put_then_catch(store):
        store.put_lab(lab)
        return AgentTools(store).claim_work_order("absent-order", "agent")

    assert "error" in run_store(put_then_catch, write=True)
    with pytest.raises(NotFound):
        run_store(lambda store: store.get_lab(lab.id))
    with pytest.raises(HostedStorageError, match="write transaction"):
        run_store(lambda store: store.put_lab(lab))


def test_concurrent_clients_and_reopened_approval_history(
    local_store, uvvis_lab_dict, b12_experiment_dict,
):
    def seed(store):
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        exp = experiment_from_dict(b12_experiment_dict)
        store.put_experiment(exp)
        return WorkOrders(store).create(exp.id, "run_plan", "Measure absorbance").id

    order = run_store(seed, write=True)
    start = Barrier(2)

    def claim(worker):
        start.wait(timeout=5)
        result = run_store(lambda store: AgentTools(store).claim_work_order(order, worker), write=True)
        return worker, result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["a", "b"]))
    (winner,) = [worker for worker, result in results if "error" not in result]
    artifact = run_store(lambda store: AgentTools(store).get_work_order_context(order))["artifact_example"]
    submitted = run_store(
        lambda store: AgentTools(store).submit_artifact(order, winner, artifact), write=True,
    )
    approved = run_store(
        lambda store: WorkOrders(store).approve(order, "reviewer", submitted["submission"]), write=True,
    )
    history = run_store(lambda store: WorkOrders(store).history(order))
    assert approved.released_submission == 1
    assert [entry["event"] for entry in history] == ["created", "claimed", "submitted", "approved"]
    assert history[-1]["note"] == submitted["artifact_digest"]


def test_remote_driver_carries_baton_and_never_replays_lost_commit():
    paths = []

    def server(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/v3/cursor"
        paths.append(body["batch"]["steps"][0]["stmt"]["sql"])
        if len(paths) == 1:
            assert request.url.host == "example.turso.io" and body["baton"] is None
            entries = [
                {"baton": "stream-1", "base_url": "https://node.turso.io"},
                {"type": "step_begin", "step": 0, "cols": []},
                {"type": "step_end", "affected_row_count": 0},
            ]
            return httpx.Response(200, text="\n".join(map(json.dumps, entries)))
        assert request.url.host == "node.turso.io" and body["baton"] == "stream-1"
        raise httpx.ReadTimeout("test response lost", request=request)

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        session = _HttpSession("libsql://example.turso.io", "test-token", client)
        with pytest.raises(turso.DatabaseError, match="session interrupted"):
            with turso.Connection(session, isolation_level=None) as db:
                db.execute("BEGIN IMMEDIATE")
                assert db.in_transaction
        db.close()
        assert paths == ["BEGIN IMMEDIATE", "COMMIT"]


def test_cleartext_and_cross_domain_session_urls_are_rejected():
    with httpx.Client() as client:
        with pytest.raises(HostedStorageError, match="HTTPS"):
            _HttpSession("http://example.test", "test-token", client)
        session = _HttpSession("libsql://example.turso.io", "test-token", client)
        with pytest.raises(HostedStorageError, match="origin"):
            session._update_stream("stream-1", "https://different.example.test")
