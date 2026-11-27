from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from labfactory.artifacts import ARTIFACT_EXAMPLES
from labfactory.context import canonical_digest
from labfactory.hosted import application, make_portal
from labfactory.hosted_auth import SESSION_COOKIE, password_hash, token_digest
from labfactory.store import Store
from labfactory.workorders import WorkOrders


def test_api_only_host_returns_404_for_unregistered_routes(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/missing").status_code == 404


def test_combined_portal_mount_preserves_api_and_mcp_routes(tmp_path, monkeypatch):
    public = tmp_path / "public"
    archive = public / "evolve" / "b12"
    archive.mkdir(parents=True)
    (public / "index.html").write_text("<h1>Reviewer</h1>")
    (archive / "index.html").write_text("<h1>Archived B12</h1>")
    # Files cannot shadow service namespaces, even for an unregistered API path.
    (public / "api").mkdir()
    (public / "api" / "missing").write_text("not an API response")
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "orders.sqlite"))
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.setenv("LABFACTORY_AGENTS", "{}")
    with TestClient(make_portal(public)) as local:
        assert local.get("/").raise_for_status().text == "<h1>Reviewer</h1>"
        assert local.get("/evolve/b12/").raise_for_status().text == "<h1>Archived B12</h1>"
        assert local.get("/api/experiments").raise_for_status().json() == {"experiments": []}
        missing = local.get("/api/missing")
        assert missing.status_code == 404 and "error" in missing.json()
        for path in ("/mcp", "/mcp/"):
            assert local.post(path, json={}).status_code == 401


def test_b12_browser_example_checks_approval_and_stores_result(client):
    assert client.get("/api/b12").status_code == 401
    assert client.post("/api/b12/orders", json={}).status_code == 401
    login(client)
    assert client.get("/api/b12").json()["orders"] == []
    order = client.post("/api/b12/orders", json={})
    assert order.status_code == 201
    id = order.json()["id"]
    path = f"/api/b12/orders/{id}/readings"
    detail = client.get(f"/api/orders/{id}?submission=latest").json()
    sub, = detail["submissions"]
    assert sub["worker"] == "Codex (bundled example)"
    assert sub["artifact_digest"] == canonical_digest(sub["artifact"])
    assert sub["rendered"] == sub["artifact"]["source"]
    assert sub["rendered"] == (Path(__file__).parents[1] / "src/labfactory/b12_example.py").read_text()
    assert any(check["name"] == "Alternate slope" and check["passed"] for check in sub["results"])
    assert all(check["passed"] for check in sub["results"])
    assert client.post(path, json={"readings": [0.1]}).status_code == 400
    assert client.post(path, json={"readings": [0.102, 0.1024, 0.1028]},
                       headers={"Origin": "https://external.test"}).status_code == 403
    dataset = client.post(path, json={"readings": [0.102, 0.1024, 0.1028]}).json()
    assert dataset["result"] is None
    run = f"{path}/{dataset['id']}/run"
    assert client.post(run, json={"submission": 1}).status_code == 409
    assert client.post(f"/api/orders/{id}/approve", json={"submission": 1, "expected_reviewer": "Ada"}).status_code == 200
    assert client.post(run, json={"submission": 2}).status_code == 409
    receipt = client.post(run, json={"submission": 1}).json()
    assert receipt["status"] == "estimated" and receipt["concentration_mg_l"] == pytest.approx(16)
    assert receipt["approved_by"] == "Ada" and receipt["artifact_digest"] == sub["artifact_digest"]
    assert client.post(run, json={"submission": 1}).json() == receipt
    outlier = client.post(path, json={"readings": [0.09, 0.10, 0.16]}).json()
    withheld = client.post(f"{path}/{outlier['id']}/run", json={"submission": 1}).json()
    assert withheld["status"] == "withheld" and withheld["concentration_mg_l"] is None
    assert "Replicate 3" in withheld["reason"]
    assert len(client.get(path).json()["readings"]) == 2
    assert client.get("/api/b12").json()["orders"][0]["status"] == "released"


def test_new_agent_analysis_remains_open_for_external_worker(client):
    login(client)
    assert client.post("/api/example", json={}).status_code == 201
    unsupported = client.post("/api/orders", json={
        "experiment_id": "b12-vial-a", "kind": "analysis_app", "objective": "Analyze uncalibrated readings",
    })
    assert unsupported.status_code == 409 and "calibration" in unsupported.json()["error"]
    res = client.post("/api/b12/orders", json={"mode": "agent"})
    assert res.status_code == 201
    detail = client.get("/api/orders/" + res.json()["id"]).json()
    assert detail["order"]["status"] == "open" and not detail["submissions"]


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


def test_public_review_without_reviewer_credentials_or_cookies(client, monkeypatch):
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.delenv("LABFACTORY_REVIEWERS")
    monkeypatch.delenv("LABFACTORY_SESSION_KEY")
    session = client.get("/api/session")
    assert session.status_code == 200
    assert session.json()["reviewer"] == "Public reviewer"
    assert session.json()["access_mode"] == "public"
    assert SESSION_COOKIE not in session.cookies
    assert client.get("/api/orders").json() == {"orders": []}
    login_response = client.post("/api/login", json={"name": "Ada", "password": "unused"})
    assert login_response.status_code == 200
    assert login_response.json()["reviewer"] == "Public reviewer"
    assert SESSION_COOKIE not in login_response.cookies
    assert client.post("/api/logout", json={}).status_code == 409
    assert client.get("/api/session").json()["reviewer"] == "Public reviewer"
    assert client.post("/api/example", json={}, headers={"Origin": "https://another.example"}).status_code == 403
    del client.headers["Origin"]
    assert client.post("/api/example", json={}).status_code == 403
    assert client.get("/api/orders").json() == {"orders": []}


def test_public_review_preserves_named_history_and_attributes_numbered_approval(client, monkeypatch):
    login(client)
    old_order = client.post("/api/example", json={}).json()["id"]
    old_path = "/api/orders/" + old_order
    submit_candidate(old_order, "run_plan", "spectrometer-agent", 550)
    assert client.post(old_path + "/approve", json={"submission": 1}).status_code == 200
    old_history = client.get(old_path).json()["history"]
    assert old_history[-1]["actor"] == "Ada"

    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    assert SESSION_COOKIE in client.cookies
    assert client.get("/api/session").json()["reviewer"] == "Public reviewer"
    assert client.get(old_path).json()["history"] == old_history
    client.cookies.clear()
    order = client.post("/api/example", json={}).json()["id"]
    path = "/api/orders/" + order
    submit_candidate(order, "run_plan", "spectrometer-agent", 550)
    assert client.post(path + "/reject", json={"submission": 1, "reason": "Revise the setting."}).status_code == 200
    second = submit_candidate(order, "run_plan", "spectrometer-agent", 550.0004)
    review = client.get(path, params={"submission": "latest"}).json()["submissions"][0]
    assert (review["number"], review["artifact_digest"]) == (2, canonical_digest(second))
    assert client.post(path + "/approve", json={"submission": 1}).status_code == 409
    assert client.post(path + "/approve", json={"submission": 2, "expected_reviewer": "Ada"}).status_code == 409
    assert client.post(path + "/approve", json={"submission": 2, "expected_reviewer": "Public reviewer"}).status_code == 200
    released = client.get(path).json()
    assert released["order"]["released_submission"] == 2
    approved = released["history"][-1]
    assert (approved["event"], approved["actor"], approved["submission"], approved["note"]) == (
        "approved", "Public reviewer", 2, review["artifact_digest"],
    )
    monkeypatch.delenv("LABFACTORY_PUBLIC_REVIEW")
    assert client.get(path).status_code == 401


def test_public_review_keeps_mcp_worker_only(client, monkeypatch):
    login(client)
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.delenv("LABFACTORY_REVIEWERS")
    monkeypatch.delenv("LABFACTORY_SESSION_KEY")
    del client.headers["Origin"]
    client.headers["Accept"] = "application/json, text/event-stream"
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert client.post("/mcp", json=rpc).status_code == 401
    assert client.post("/mcp", json=rpc, headers={"Authorization": "Bearer invalid"}).status_code == 401
    allowed = client.post("/mcp", json=rpc, headers={"Authorization": "Bearer " + AGENT_TOKEN})
    assert allowed.status_code == 200
    assert {tool["name"] for tool in allowed.json()["result"]["tools"]} == {
        "list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact",
    }


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


def test_experiment_discovery_and_pinned_order_context(client, uvvis_lab_dict, b12_experiment_dict):
    experiment = {**b12_experiment_dict, "id": "rack 1/α?#"}
    detail_url = "/api/experiments/" + quote(experiment["id"], safe="")
    for path in ("/api/experiments", detail_url, "/api/orders/WO-1/context"):
        assert client.get(path).status_code == 401
    login(client)
    assert client.get("/api/experiments").json() == {"experiments": []}
    assert client.get(detail_url).status_code == client.get("/api/orders/WO-1/context").status_code == 404
    assert client.post("/api/context/lab", json=uvvis_lab_dict).is_success
    assert client.post("/api/context/experiment", json=experiment).is_success
    assert client.post("/api/b12/orders", json={"mode": "agent"}).is_success
    assert client.get("/api/experiments").json() == {"experiments": [
        {"id": experiment["id"], "title": experiment["title"], "lab_id": experiment["lab_id"], "revision": 1}
    ]}
    payload = {"experiment_id": experiment["id"], "kind": "procedure", "objective": "Review a cuvette procedure"}
    procedure = client.post("/api/orders", json=payload).json()["id"]
    assert client.post("/api/orders", json={**payload, "kind": "run_plan"}).is_success
    assert client.post("/api/context/experiment", json={**experiment, "title": "Revised title"}).is_success
    assert client.post("/api/context/lab", json={**uvvis_lab_dict, "documents": []}).is_success
    detail = client.get(detail_url).json()
    assert [row["id"] for row in detail["orders"]] == [procedure]
    assert detail["experiment"]["title"] == "Revised title" and detail["lab"]["documents"] == []
    assert detail["lab_revision"] == detail["experiment_revision"] == 2
    latest, = client.get("/api/experiments").json()["experiments"]
    assert latest["title"] == "Revised title" and latest["revision"] == 2
    pinned = client.get(f"/api/orders/{procedure}/context").json()
    assert pinned == {"experiment": experiment, "experiment_revision": 1, "lab": uvvis_lab_dict, "lab_revision": 1}


def test_order_creation_requires_current_displayed_revisions_when_supplied(client):
    login(client)
    assert client.post("/api/example", json={}).is_success
    payload = {"experiment_id": "b12-vial-a", "kind": "procedure", "objective": "Review cuvette handling"}
    detail = client.get("/api/experiments/b12-vial-a").json()
    assert client.post("/api/context/lab", json={**detail["lab"], "name": "Revised lab"}).is_success
    for invalid in ({"expected_lab_revision": 2}, {"expected_experiment_revision": 1},
                    {"expected_lab_revision": True, "expected_experiment_revision": 1},
                    {"expected_lab_revision": 2, "expected_experiment_revision": 0}):
        assert client.post("/api/orders", json={**payload, **invalid}).status_code == 400
    for exp_revision, lab_revision in ((1, 1), (2, 2)):
        stale = {**payload, "expected_experiment_revision": exp_revision, "expected_lab_revision": lab_revision}
        assert client.post("/api/orders", json=stale).status_code == 409
    assert client.get("/api/experiments/b12-vial-a").json()["orders"] == []
    current = client.post("/api/orders", json={**payload, "expected_experiment_revision": 1, "expected_lab_revision": 2})
    assert current.status_code == 201
    order, = client.get("/api/experiments/b12-vial-a").json()["orders"]
    assert (order["id"], order["experiment_revision"], order["lab_revision"]) == (current.json()["id"], 1, 2)


def test_experiment_lists_only_its_linked_analyses_newest_first(client, uvvis_lab_dict, b12_experiment_dict):
    login(client)
    client.post("/api/context/lab", json=uvvis_lab_dict).raise_for_status()
    procedures = {}
    for experiment_id in ("assay-one", "assay-two"):
        client.post("/api/context/experiment", json={**b12_experiment_dict, "id": experiment_id}).raise_for_status()
        order = client.post("/api/orders", json={
            "experiment_id": experiment_id, "kind": "procedure", "objective": "Read the reference solution",
        }).raise_for_status().json()["id"]
        submit_candidate(order, "procedure", "worker-a", 550)
        client.post(f"/api/orders/{order}/approve", json={"submission": 1}).raise_for_status()
        procedures[experiment_id] = order

    upload = {
        "objective": "Calculate concentration", "protocol_name": "protocol.txt", "protocol": "Use each signal.",
        "csv_name": "readings.csv", "csv": "id,role,signal,known,factor\nc,control,5,,1\nu,unknown,3,,1\n",
        "mapping": {name: name for name in ("id", "role", "signal", "known", "factor")},
        "unit": "mg/L", "range_gate": False, "control_expected": 5, "control_tolerance": 0.1,
    }
    expected = {"assay-one": [], "assay-two": []}
    for experiment_id in ("assay-one", None, "assay-two", "assay-one"):
        request = dict(upload)
        if experiment_id:
            request["procedure_order_id"] = procedures[experiment_id]
        analysis_id = client.post("/api/analysis/orders", json=request).raise_for_status().json()["id"]
        if experiment_id:
            expected[experiment_id].insert(0, {"id": analysis_id, "procedure_order_id": procedures[experiment_id],
                                               "status": "open"})
    for experiment_id, links in expected.items():
        detail = client.get("/api/experiments/" + experiment_id).raise_for_status().json()
        assert detail["analyses"] == links
        assert [row["id"] for row in detail["orders"]] == [procedures[experiment_id]]
    assert {r["id"] for r in client.get("/api/experiments").json()["experiments"]} == set(procedures)


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


@pytest.mark.parametrize("public", [False, True])
def test_requeue_uses_displayed_claim_and_reviewer_policy(client, monkeypatch, public):
    if public:
        monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
        monkeypatch.delenv("LABFACTORY_REVIEWERS")
        monkeypatch.delenv("LABFACTORY_SESSION_KEY")
    else:
        denied = client.post("/api/orders/WO-1/requeue", json={"claim_id": 1, "reason": "Timeout"},
                             headers={"Authorization": "Bearer " + AGENT_TOKEN})
        assert denied.status_code == 401
        login(client)
    reviewer = "Public reviewer" if public else "Ada"
    created = client.post("/api/example", json={})
    assert created.status_code == 201
    id = created.json()["id"]
    path = f"/api/orders/{id}"
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        WorkOrders(store).claim(id, "spectrometer-agent")
        with store.transaction():
            store.connection.execute(
                "UPDATE events SET at='2026-11-25 19:20:21' WHERE work_order_id=? AND event='claimed'", (id,),
            )
    detail = client.get(path + "?submission=latest").json()
    assert detail["submissions"] == []
    assert detail["order"]["claimed_at"] == "2026-11-25T19:20:21Z"
    payload = {"claim_id": detail["order"]["claim_id"], "reason": "Timeout", "expected_reviewer": reviewer}
    assert client.post(path + "/requeue", json={**payload, "claim_id": True}).status_code == 400
    assert client.post(path + "/requeue", json={**payload, "reason": " "}).status_code == 409
    assert client.post(path + "/requeue", json={**payload, "expected_reviewer": "Other"}).status_code == 409
    assert client.post(path + "/requeue", json=payload, headers={"Origin": "https://other.test"}).status_code == 403
    assert client.post(path + "/requeue", json=payload).json() == {"id": id, "status": "open"}
    detail = client.get(path).json()
    assert detail["order"]["claim_id"] is None and detail["order"]["worker"] is None
    assert detail["order"]["claimed_at"] is None
    event = detail["history"][-1]
    assert event["event"] == "requeued" and event["actor"] == reviewer
    assert "spectrometer-agent" in event["note"] and "Timeout" in event["note"]
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        WorkOrders(store).claim(id, "spectrometer-agent")
        with store.transaction():
            # A clock correction must not make the first claim look active again.
            store.connection.execute(
                "UPDATE events SET at='2026-11-25 18:19:20' WHERE rowid=last_insert_rowid()",
            )
    replacement = client.get(path).json()
    assert replacement["order"]["claim_id"] != payload["claim_id"]
    assert replacement["order"]["claimed_at"] == "2026-11-25T18:19:20Z"
    assert client.post(path + "/requeue", json=payload).status_code == 409
    assert client.get(path).json() == replacement
