from copy import deepcopy
import json
import os

import pytest
from starlette.testclient import TestClient

from labfactory.artifacts import ARTIFACT_EXAMPLES
from labfactory.context import canonical_digest
from labfactory.hosted import application
from labfactory.hosted_auth import SESSION_COOKIE, password_hash, token_digest
from labfactory.store import Store
from labfactory.workorders import WorkOrders


ORIGIN = "https://localhost"
PASSWORD = "disposable test reviewer password"
AGENT_TOKEN = "disposable test worker token"


@pytest.fixture(scope="module")
def reviewer_record():
    return json.dumps({"Ada": password_hash(PASSWORD)})


@pytest.fixture
def client(tmp_path, monkeypatch, reviewer_record):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "portal.sqlite"))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", reviewer_record)
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"spectrometer-agent": token_digest(AGENT_TOKEN)}))
    with TestClient(application, base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        yield session


def login(client):
    res = client.post("/api/login", json={"name": "Ada", "password": PASSWORD})
    assert res.status_code == 200
    assert res.json() == {"reviewer": "Ada", "agent_names": ["spectrometer-agent"]}
    return res


def submit_candidate(order_id, kind, worker, wavelength):
    artifact = deepcopy(ARTIFACT_EXAMPLES[kind])
    step = artifact["steps"][-1]
    action = step if kind == "run_plan" else step["action"]
    action["settings"][0]["value"] = wavelength
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        orders = WorkOrders(store)
        orders.claim(order_id, worker)
        assert orders.submit(order_id, worker, artifact).passed
    return artifact


def test_named_login_role_isolation_and_signout(client):
    assert client.get("/api/session").json() == {"reviewer": None}
    for name, password in [("Ada", "wrong"), ("nobody", PASSWORD)]:
        res = client.post("/api/login", json={"name": name, "password": password})
        assert res.status_code == 401
        assert SESSION_COOKIE not in res.cookies

    # A worker can authenticate to MCP without gaining reviewer access.
    client.headers["Authorization"] = "Bearer " + AGENT_TOKEN
    for path in ["/api/orders", "/api/orders/WO-1"]:
        assert client.get(path).status_code == 401
    for path in ["/api/example", "/api/orders", "/api/context/lab", "/api/context/experiment",
                 "/api/orders/WO-1/approve", "/api/orders/WO-1/reject"]:
        assert client.post(path, json={}).status_code == 401
    del client.headers["Authorization"]
    res = login(client)
    cookie = res.headers["set-cookie"].lower()
    assert SESSION_COOKIE.lower() in cookie
    for attribute in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attribute in cookie
    data = client.get("/api/orders")
    assert data.json() == {"orders": []}
    assert "no-store" in data.headers["cache-control"]
    assert client.get("/api/orders/missing").status_code == 404
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    assert client.post("/api/logout", json={}).json() == {"reviewer": None}
    assert SESSION_COOKIE not in client.cookies
    assert client.get("/api/orders").status_code == 401


def test_reviewer_password_rotation_revokes_existing_session(client, monkeypatch):
    login(client)
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": password_hash("replacement password")}))
    assert client.get("/api/session").json() == {"reviewer": None}
    assert client.get("/api/orders").status_code == 401


def test_writes_require_same_origin_json_object(client):
    login(client)
    assert client.post("/api/example", headers={"Origin": "https://another.example"}, json={}).status_code == 403
    del client.headers["Origin"]
    assert client.post("/api/example", json={}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/example", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    for body in ["[]", "{", '{"id":"a","id":"b"}']:
        res = client.post("/api/context/lab", content=body, headers={"Content-Type": "application/json"})
        assert res.status_code == 400
        assert res.json()["error"]
    assert client.get("/api/orders").json() == {"orders": []}


def test_context_imports_pin_the_order_and_render_procedure(client, uvvis_lab_dict, b12_experiment_dict):
    login(client)
    for kind, record in [("lab", uvvis_lab_dict), ("experiment", b12_experiment_dict)]:
        res = client.post("/api/context/" + kind, json=record)
        assert res.status_code == 200
        assert res.json()["id"] == record["id"]
        assert res.json()["revision"] == 1
    created = client.post("/api/orders", json={
        "experiment_id": b12_experiment_dict["id"], "kind": "procedure", "objective": "Review cuvette handling",
    })
    assert created.status_code == 201
    order_id = created.json()["id"]
    b12_experiment_dict["title"] = "Revised reference solution"
    uvvis_lab_dict["name"] = "Revised teaching lab"
    assert client.post("/api/context/lab", json=uvvis_lab_dict).json()["revision"] == 2
    assert client.post("/api/context/experiment", json=b12_experiment_dict).json()["revision"] == 2
    artifact = submit_candidate(order_id, "procedure", "worker-a", 550.0004)
    detail = client.get("/api/orders/" + order_id).json()
    assert [(e["event"], e["actor"]) for e in detail["history"] if e["event"] == "created"] == [("created", "Ada")]
    assert detail["order"]["experiment_revision"] == detail["order"]["lab_revision"] == 1
    sub, = detail["submissions"]
    assert sub["artifact_digest"] == canonical_digest(artifact)
    for expected in ("sop-cuvette", "b12-protocol", "1 mL", "uvvis-1", "read_absorbance", "550.0004 nm"):
        assert expected in sub["rendered"]
    # The example endpoint reuses the latest imported records.
    example = client.post("/api/example", json={})
    assert example.status_code == 201
    example_detail = client.get("/api/orders/" + example.json()["id"]).json()
    assert [(e["event"], e["actor"]) for e in example_detail["history"]] == [("created", "Ada")]
    second = example_detail["order"]
    assert second["lab_revision"] == second["experiment_revision"] == 2


def test_numbered_review_preserves_submissions_and_records_exact_digest(client):
    login(client)
    res = client.post("/api/example", json={})
    assert res.status_code == 201
    order_id = res.json()["id"]
    path = "/api/orders/" + order_id
    first = submit_candidate(order_id, "run_plan", "worker-a", 550)
    for number in [False, 0, 1.0, "1", None]:
        assert client.post(path + "/approve", json={"submission": number}).status_code == 400
    assert client.post(path + "/reject", json={"submission": 1, "reason": " "}).status_code == 409
    res = client.post(path + "/reject", json={"submission": 1, "reason": "Use the revised setpoint."})
    assert res.json() == {"id": order_id, "status": "open"}
    second = submit_candidate(order_id, "run_plan", "worker-b", 550.0004)
    stale = client.post(path + "/approve", json={"submission": 1})
    assert stale.status_code == 409 and "latest" in stale.json()["error"]
    review = client.get(path).json()
    assert review["order"]["status"] == "in_review"
    assert [s["artifact_digest"] for s in review["submissions"]] == [canonical_digest(first), canonical_digest(second)]
    first_sub, second_sub = review["submissions"]
    assert (first_sub["number"], first_sub["worker"], first_sub["artifact"]) == (1, "worker-a", first)
    assert (second_sub["number"], second_sub["worker"], second_sub["artifact"]) == (2, "worker-b", second)
    assert all(check["passed"] and check["detail"] for check in second_sub["results"])
    assert "550.0004 nm" in second_sub["rendered"]
    assert client.post(path + "/approve", json={"submission": 2}).json() == {"id": order_id, "status": "released"}
    final = client.get(path).json()
    assert final["order"]["released_submission"] == 2
    decisions = [(e["event"], e["actor"], e["submission"], e["note"]) for e in final["history"]
                 if e["event"] in ("approved", "rejected")]
    assert decisions == [("rejected", "Ada", 1, "Use the revised setpoint."), ("approved", "Ada", 2, canonical_digest(second))]


def test_review_modal_binds_the_visible_reviewer_after_another_tab_signs_in(client, monkeypatch):
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({
        "Ada": password_hash(PASSWORD), "Grace": password_hash("second reviewer password"),
    }))
    login(client)
    order_id = client.post("/api/example", json={}).json()["id"]
    submit_candidate(order_id, "run_plan", "spectrometer-agent", 550)
    path = "/api/orders/" + order_id
    assert client.post("/api/login", json={"name": "Grace", "password": "second reviewer password"}).status_code == 200
    for action, fields in [("approve", {}), ("reject", {"reason": "Recheck."})]:
        stale = client.post(path + "/" + action, json={"submission": 1, "expected_reviewer": "Ada", **fields})
        assert stale.status_code == 409 and "Reviewer changed" in stale.json()["error"]
    assert client.get(path).json()["order"]["status"] == "in_review"
    assert client.post(path + "/approve", json={"submission": 1, "expected_reviewer": "Grace"}).status_code == 200
    assert client.get(path).json()["history"][-1]["actor"] == "Grace"


def test_large_order_uses_indexed_submission_and_history_pages(client):
    login(client)
    order_id = client.post("/api/example", json={}).json()["id"]
    path = "/api/orders/" + order_id
    artifact = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        orders = WorkOrders(store)
        for n in range(1, 25):
            orders.claim(order_id, "worker")
            artifact["steps"][0]["settings"][0]["value"] = 500 + n
            assert orders.submit(order_id, "worker", artifact).passed
            orders.reject(order_id, "Ada", n, "Review notes " * 18000)
    complete = client.get(path)
    assert len(complete.content) > 4_500_000
    assert complete.headers["content-type"] == "application/json"
    assert "content-length" not in complete.headers
    full = complete.json()
    page = client.get(path, params={"submission": "latest"}).json()
    assert [s["number"] for s in page["submissions"]] == [24]
    assert page["older_submission"] == 23
    old = client.get(path, params={"submission": page["older_submission"]}).json()
    assert old["submissions"] == full["submissions"][22:23] and old["history"] == []
    assert client.get(path, params={"submission": 1}).json()["older_submission"] is None
    assert client.get(path, params={"submission": 25}).status_code == 404
    assert client.get(path, params={"before_event": "invalid"}).status_code == 400
    history = page["history"]
    while page["before_event"]:
        page = client.get(path, params={"before_event": page["before_event"]}).json()
        assert page["submissions"] == []
        history = page["history"] + history
    assert history == full["history"]
