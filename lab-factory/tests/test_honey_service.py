from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from labfactory import honey_service as service
from labfactory.agent import AgentTools
from labfactory.cli import _show
from labfactory.context import canonical_digest, canonical_json
from labfactory.hosted import application
from labfactory.hosted_auth import password_hash, token_digest
from labfactory.store import Store
from labfactory.workorders import WorkOrderError, WorkOrders


@pytest.fixture
def candidate():
    return json.loads((Path(__file__).parents[1] / "examples/honey-analysis.json").read_text())


def test_pinned_evidence_in_generic_creation_and_rejected_analysis(store, candidate, monkeypatch):
    first = service.create_order(store, "Operator")["id"]
    orders = WorkOrders(store)
    new = orders.create(service.EXPERIMENT_ID, "analysis_app", "Test duplicate simulated readings")
    agent = AgentTools(store)
    ctx = agent.get_work_order_context(new.id)
    brief = ctx["reference_brief"]
    assert brief == store.reference_brief(first)
    assert {s["id"] for s in brief["findings"]} == set(service.SOURCE_IDS)
    assert all(s["url"].startswith("https://") and s["locator"] for s in brief["findings"])
    assert all(v == [] for v in ctx["artifact_example"].values())
    assert candidate["table"] not in list(ctx.values()) and "slope" not in ctx["instructions"]
    # Previous context and recorded source use survive newer catalog and lab revisions.
    monkeypatch.setattr(service, "current_snapshot", lambda: {"new": "edition"})
    lab, exp = orders.pinned_context(new.id)
    store.put_lab(replace(lab, name="Updated instrument inventory"))
    store.put_experiment(replace(exp, goal="Updated lab protocol"))
    agent.claim_work_order(new.id, "A")
    failed = agent.submit_artifact(new.id, "A", {"source": "incorrect artifact"})
    assert not failed["passed"] and failed["status"] == "in_progress"
    assert "incorrect artifact" in _show(orders, new.id)
    first_valid = agent.submit_artifact(new.id, "A", candidate)
    assert first_valid["passed"] and first_valid["submission"] == 2
    orders.reject(new.id, "R", 2, "Clarify the research paper's role")
    agent.claim_work_order(new.id, "B")
    ctx = agent.get_work_order_context(new.id)
    assert ctx["reference_brief"] == brief and ctx["previous_rejection"]["artifact"] == candidate
    assert ctx["previous_rejection"]["reason"] == "Clarify the research paper's role"
    revised = deepcopy(candidate)
    revised["citations"][0]["use"] += " Scope is limited to this simulated instrument."
    second_valid = agent.submit_artifact(new.id, "B", revised)
    assert second_valid["passed"] and second_valid["submission"] == 3
    with pytest.raises(WorkOrderError, match="latest"):
        orders.approve(new.id, "R", 2)
    orders.approve(new.id, "R", 3)
    receipt = service.run(store, new.id, "Reviewer", [1.4940, 1.4940], 3)
    assert receipt["moisture_pct"] == 17.0
    assert receipt["reference_brief_digest"] == canonical_digest(brief)
    assert receipt["artifact_digest"] == canonical_digest(revised)


def test_release_and_source_integrity_protect_execution(store, candidate):
    order = service.create_order(store, "R")["id"]
    orders = WorkOrders(store)
    agent = AgentTools(store)
    agent.claim_work_order(order, "Writer")
    assert agent.submit_artifact(order, "Writer", candidate)["passed"]
    with pytest.raises(WorkOrderError, match="release"):
        service.run(store, order, "R", [1.4940, 1.4940])
    orders.approve(order, "R", 1)
    with pytest.raises(WorkOrderError, match="submission"):
        service.run(store, order, "R", [1.4940, 1.4940], 2)
    with store.transaction() as db:
        db.execute("UPDATE events SET note='corrupt' WHERE event='approved' AND work_order_id=?", (order,))
    with pytest.raises(WorkOrderError, match="digest"):
        service.run(store, order, "R", [1.4940, 1.4940], 1)
    with store.transaction() as db:
        db.execute("UPDATE events SET note=? WHERE event='approved' AND work_order_id=?",
                   (canonical_digest(candidate), order))
        brief = store.reference_brief(order)
        brief["findings"][0]["summary"] = "Changed source record"
        db.execute("UPDATE reference_briefs SET snapshot=? WHERE work_order_id=?", (canonical_json(brief), order))
    with pytest.raises(WorkOrderError, match="pinned"):
        service.run(store, order, "R", [1.4940, 1.4940], 1)
    assert service.list_runs(store.connection, order) == []


def test_review_run_and_persist_over_http(tmp_path, monkeypatch, candidate):
    db = tmp_path / "lab.sqlite"
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(db))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "a-disposable-session-key-for-testing")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Reviewer": password_hash("disposable-reviewer-test")}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"Evidence agent": token_digest("disposable-agent-token")}))
    origin = "https://localhost"
    with TestClient(application, base_url=origin, headers={"Origin": origin}) as client:
        assert client.get("/api/honey").status_code == 401
        client.post("/api/login", json={"name": "Reviewer", "password": "disposable-reviewer-test"}).raise_for_status()
        assert client.get("/api/honey").json()["orders"] == []
        assert client.post("/api/honey/orders", json={"formula": "guess"}).status_code == 400
        order_id = client.post("/api/honey/orders", json={}).raise_for_status().json()["id"]
        path = "/api/honey/orders/" + order_id
        initial = client.get(path).raise_for_status().json()
        assert initial["order"]["status"] == "open" and initial["submissions"] == initial["runs"] == []
        with Store(db) as store:
            agent = AgentTools(store)
            assert agent.get_work_order_context(order_id)["reference_brief"] == initial["reference_brief"]
            agent.claim_work_order(order_id, "Evidence agent")
            assert agent.submit_artifact(order_id, "Evidence agent", candidate)["passed"]
        sub, = client.get(path).json()["submissions"]
        assert json.loads(sub["rendered"]) == candidate and sub["artifact_digest"] == canonical_digest(candidate)
        payload = {"readings": [1.4940, 1.4940], "submission": 1}
        assert client.post(path + "/run", json=payload).status_code == 409
        approved = client.post(f"/api/orders/{order_id}/approve", json={"expected_reviewer": "Reviewer", "submission": 1})
        assert approved.status_code == 200 and approved.json()["status"] == "released"
        for invalid in ({"readings": [True, 1.49]}, {"readings": [1.49401, 1.49]}, {**payload, "submission": None}):
            assert client.post(path + "/run", json=invalid).status_code == 400
        assert client.post(path + "/run", json={**payload, "submission": 2}).status_code == 409
        receipt = client.post(path + "/run", json=payload).raise_for_status().json()
        assert receipt["status"] == "estimated" and receipt["moisture_pct"] == 17.0 and receipt["simulated"]
        assert receipt["artifact_digest"] == sub["artifact_digest"] and receipt["approved_by"] == "Reviewer"
        assert receipt["worker"] == "Evidence agent" and receipt["submission"] == 1
        assert receipt["source_digests"] == {s["id"]: s["digest"] for s in initial["reference_brief"]["findings"]}
        assert receipt == client.post(path + "/run", json=payload).json()
        withheld = client.post(path + "/run", json={"readings": [1.51, 1.49]}).raise_for_status().json()
        assert withheld["status"] == "withheld" and withheld["moisture_pct"] is None
        assert client.get(path).json()["runs"] == [withheld, receipt]
        assert client.get("/api/orders/" + order_id + "?submission=latest").json()["runs"] == [withheld, receipt]
        assert client.get("/api/honey").json()["orders"][0]["status"] == "released"
