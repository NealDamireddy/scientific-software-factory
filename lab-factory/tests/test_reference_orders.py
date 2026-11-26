from copy import deepcopy
import json
import sqlite3

import pytest
from starlette.testclient import TestClient

from labfactory import reference_orders, references
from labfactory.agent import AgentTools
from labfactory.blob_storage import _mutate
from labfactory.context import ContextError
from labfactory.hosted import application
from labfactory.hosted_auth import password_hash, token_digest
from labfactory.store import Store
from labfactory.workorders import WorkOrderError, WorkOrders


def selection(result, *sources):
    return {
        "instrument": result["instrument"]["id"], "q": result["query"],
        "catalog_digest": result["catalog_digest"],
        "selections": [{"id": source["id"], "digest": source["digest"]} for source in sources],
    }


def test_pinned_references_survive_catalog_changes_and_are_citeable(tmp_path, monkeypatch):
    path = tmp_path / "review.sqlite"
    result = references.search("thermo-orion-star-a211", "Measure the pH of water")
    manual = next(source for source in result["findings"] if source["kind"] == "manual")
    others = [source for source in result["findings"] if source["id"] != manual["id"]]
    assert others
    with Store(path) as store:
        request = selection(result, manual)
        request["q"] = "  " + result["query"] + "  "
        order_id = reference_orders.create_order(store, "Reviewer", request)["id"]
    monkeypatch.setattr(references, "search", lambda *args: pytest.fail("Re-read live catalog"))
    with Store(path) as store:
        agent = AgentTools(store)
        context = agent.get_work_order_context(order_id)
        brief = context["reference_brief"]
        assert brief["query"] == result["query"] and brief["findings"] == [manual]
        assert all(set(row["source_ids"]) <= {manual["id"]} for row in brief["brief"])
        assert context["work_order"]["kind"] == "procedure"
        device, = context["lab"]["instruments"]
        assert device["commands"] == [] and device["parameters"] == []
        doc, = context["experiment"]["documents"]
        assert (doc["id"], doc["source"]) == (manual["id"], manual["url"])
        assert manual["digest"] in doc["text"] and manual["scope"] in doc["text"]
        agent.claim_work_order(order_id, "Agent")
        artifact = context["artifact_example"]
        artifact["steps"][0]["citations"] = [others[0]["id"]]
        assert not agent.submit_artifact(order_id, "Agent", artifact)["passed"]
        artifact["steps"][0]["citations"] = [manual["id"]]
        assert agent.submit_artifact(order_id, "Agent", artifact)["passed"]


@pytest.mark.parametrize("selector", ["all", "other-gravimetry"])
def test_catalog_wide_and_technique_orders_have_no_invented_device(store, selector):
    result = references.search(selector, "Determine suspended solids in water by gravimetry")
    procedure = next(s for s in result["findings"] if s["kind"] == "procedure")
    order_id = reference_orders.create_order(store, "Reviewer", selection(result, procedure))["id"]
    context = AgentTools(store).get_work_order_context(order_id)
    assert context["lab"]["instruments"] == [] and context["experiment"]["instrument_ids"] == []
    doc, = context["experiment"]["documents"]
    assert doc["kind"] == "note" and "Externally published procedure" in doc["text"]
    assert context["reference_brief"]["instrument"]["id"] == selector
    with pytest.raises(WorkOrderError, match="Assign an instrument"):
        WorkOrders(store).create(context["experiment"]["id"], "run_plan", "Collect measurements")


def test_reject_stale_unmatched_and_malformed_selections_atomically(store):
    result = references.search("thermo-orion-star-a211", "Measure the pH of water")
    source = result["findings"][0]
    request = selection(result, source)
    mismatched = references.search("agilent-cary-60", "B12")
    other_manual = next(s for s in mismatched["findings"] if s["id"] == "agilent-cary-60-user-guide")
    for change, error in [
        ({"catalog_digest": "0" * 64}, WorkOrderError),
        ({"selections": [{"id": source["id"], "digest": "0" * 64}]}, WorkOrderError),
        ({"catalog_digest": []}, ContextError),
        ({"selections": [{"id": source["id"], "digest": "invalid digest"}]}, ContextError),
        ({"selections": selection(mismatched, other_manual)["selections"]}, ContextError),
        ({"selections": request["selections"] * 2}, ContextError),
        ({"selections": []}, ContextError),
        ({"selections": [{"id": [], "digest": "bad"}]}, ContextError),
        ({"selections": [{"id": source["id"], "digest": source["digest"], "summary": "override"}]}, ContextError),
        ({"q": "   "}, ContextError),
        ({"q": " " * 300 + result["query"]}, ContextError),
    ]:
        with pytest.raises(error):
            reference_orders.create_order(store, "Reviewer", {**request, **change})
    store.connection.execute("""
        CREATE TRIGGER fail_last_write BEFORE INSERT ON reference_briefs
        BEGIN SELECT RAISE(ABORT,'Simulated write failure'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match="Simulated write failure"):
        reference_orders.create_order(store, "Reviewer", request)
    for table in ("records", "events", "reference_briefs", "work_orders"):
        assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_reference_order_round_trip_in_blob_sqlite_snapshot():
    result = references.search("other-gravimetry", "Check an analytical balance")
    selected = result["findings"][0]
    request = selection(result, selected)
    order, snapshot = _mutate(None, lambda s: reference_orders.create_order(s, "Ada", request), True)
    def read(store):
        return AgentTools(store).get_work_order_context(order["id"])
    context, writeback = _mutate(snapshot, read, False)
    assert writeback is None and context["reference_brief"]["findings"] == [selected]
    assert context["work_order"]["objective"] == request["q"]


def test_hosted_reference_flow_requires_reviewer_and_pins_exact_subset(tmp_path, monkeypatch):
    origin = "https://localhost"
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "portal.sqlite"))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": password_hash("disposable password")}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"agent": token_digest("disposable credential")}))
    with TestClient(application, base_url=origin, headers={"Origin": origin}) as client:
        assert client.get("/api/references").status_code == 401
        assert client.get("/api/references/search").status_code == 401
        assert client.post("/api/references/orders", json={}).status_code == 401
        assert client.post("/api/login", json={"name": "Ada", "password": "disposable password"}).is_success
        assert client.get("/api/references").json() == references.catalog()
        old_id = client.post("/api/example", json={}).json()["id"]
        assert "reference_brief" not in client.get("/api/orders/" + old_id).json()
        assert client.get("/api/references/search", params={"instrument": "unknown-model"}).status_code == 400
        result = client.get("/api/references/search", params={"instrument": "mettler-toledo-uv7", "q": "B12"}).json()
        request = selection(result, result["findings"][0])
        assert client.post("/api/references/orders", json=request, headers={"Origin": "https://other.test"}).status_code == 403
        stale = deepcopy(request)
        stale["selections"][0]["digest"] = "0" * 64
        assert client.post("/api/references/orders", json=stale).status_code == 409
        assert client.post("/api/references/orders", json=["malformed"]).status_code == 400
        assert client.post("/api/references/orders", json={**request, "q": " " * 301 + "B12"}).status_code == 400
        response = client.post("/api/references/orders", json=request)
        assert response.status_code == 201, response.text
        detail = client.get("/api/orders/" + response.json()["id"] + "?submission=latest").json()
        assert detail["reference_brief"]["findings"] == [result["findings"][0]]
        assert detail["order"]["objective"] == "B12"
        assert detail["history"][0]["actor"] == "Ada"


def test_experiment_requirements_are_pinned_with_a_reviewer_selection(store, monkeypatch):
    result = references.search("hach-2100qis", "Compare coagulation in jar tests")
    chosen = [next(r for r in result["findings"] if r["id"] == item["source_ids"][0]) for item in result["brief"]]
    order_id = reference_orders.create_order(store, "Reviewer", selection(result, *chosen))["id"]
    monkeypatch.setattr(references, "search", lambda *args: pytest.fail("Pinned requirements must survive a new edition"))
    brief = AgentTools(store).get_work_order_context(order_id)["reference_brief"]
    assert brief["requirements"] == result["requirements"] and "meter" in brief["requirements"]
    assert {r["id"] for r in brief["findings"]} == {r["id"] for r in chosen}
