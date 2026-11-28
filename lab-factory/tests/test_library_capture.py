import json
import os
import sqlite3

import pytest
from starlette.testclient import TestClient

from labfactory import briefing, first_draft, library, procedure_demo
from labfactory import procedure_drafts as drafts
from labfactory.agent import AgentTools
from labfactory.context import ContextError, experiment_from_dict, lab_from_dict
from labfactory.hosted import application
from labfactory.store import Store
from labfactory.workorders import WorkOrders

ORIGIN = "https://localhost"
PASSWORD = "disposable test reviewer password"
AGENT_TOKEN = "disposable test worker token"
CATALOG = "agilent-cary-60-user-guide"
QUESTION = {"needs_input": "Which temperature is specified for the reference probe?"}


def asking_order(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    b12_experiment_dict.update(id="thermal-drift", title="Probe stability", documents=[],
                               goal="Record thermal drift of the reference probe.")
    exp = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(exp)
    order = drafts.create(store, exp.id, "reviewer")
    AgentTools(store).claim_work_order(order.id, "worker")
    AgentTools(store).submit_artifact(order.id, "worker", QUESTION)
    return order.id, exp.lab_id


@pytest.fixture
def asked(store, uvvis_lab_dict, b12_experiment_dict):
    return asking_order(store, uvvis_lab_dict, b12_experiment_dict)


def rows(store):
    return [store.connection.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("library_entries", "library_texts", "work_order_library")]


def test_answer_is_captured_for_the_orders_lab(store, asked):
    order_id, lab_id = asked
    new = drafts.add_source(store, order_id, "Reviewer", "Balance worksheet", "Read the mass.")
    (entry,) = library.latest(store, lab_id)
    assert (entry["scope"], entry["title"], entry["contributed_by"]) == (
        library.lab_scope(lab_id), "Balance worksheet", "Reviewer")
    assert library.latest(store) == []
    _, experiment = WorkOrders(store).pinned_context(new)
    assert experiment.documents[-1].id.startswith("method-")
    assert experiment.documents[-1].text == "Read the mass."
    assert library.pinned(store, new) == []


def test_answer_can_name_the_catalog_source_it_comes_from(store, asked):
    order_id, lab_id = asked
    new = drafts.add_source(store, order_id, "Reviewer", "My typed title", "Read the mass.", source_id=CATALOG)
    (entry,) = library.latest(store, lab_id)
    assert entry["source_id"] == CATALOG and entry["kind"] == "manual"
    assert entry["title"] != "My typed title"
    _, experiment = WorkOrders(store).pinned_context(new)
    assert experiment.documents[-1].title == "My typed title"


def test_unknown_source_id_is_rejected_before_anything_is_saved(store, asked):
    order_id, _ = asked
    for bad in ("nope", 5):
        with pytest.raises(ContextError, match="Unknown library source"):
            drafts.add_source(store, order_id, "Reviewer", "T", "Read the mass.", source_id=bad)
    assert drafts.info(store, order_id)["next_order"] is None
    assert rows(store) == [0, 0, 0]


def test_source_id_may_name_a_source_visible_to_the_lab(store, asked):
    order_id, lab_id = asked
    entry = library.add(store, "Ada", "Shared words.", title="Shared note")
    drafts.add_source(store, order_id, "Reviewer", "T", "Read the mass.", source_id=entry["source_id"])
    assert {e["source_id"] for e in library.latest(store, lab_id)} == {entry["source_id"]}
    assert len(library.latest(store, lab_id)) == 2


def test_source_id_from_another_lab_is_rejected(store, asked):
    order_id, _ = asked
    other = library.add(store, "Ada", "Other lab text.", title="Private", lab_id="other-lab")
    with pytest.raises(ContextError, match="Unknown library source"):
        drafts.add_source(store, order_id, "Reviewer", "T", "Read the mass.", source_id=other["source_id"])
    assert drafts.info(store, order_id)["next_order"] is None


def test_oversized_answer_is_saved_but_not_captured(store, asked):
    order_id, _ = asked
    new = drafts.add_source(store, order_id, "Reviewer", "T", "x" * (library.MAX_TEXT_BYTES + 1))
    assert WorkOrders(store).get(new)
    assert rows(store) == [0, 0, 0]


def test_capture_failure_does_not_fail_the_answer(store, asked, monkeypatch):
    order_id, _ = asked
    def refuse(*args, **kwargs):
        raise ContextError("x")
    monkeypatch.setattr(library, "append", refuse)
    assert WorkOrders(store).get(drafts.add_source(store, order_id, "Reviewer", "T", "Read the mass."))


def test_unexpected_capture_failure_propagates(store, asked, monkeypatch):
    order_id, _ = asked
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("x")
    monkeypatch.setattr(library, "append", broken)
    with pytest.raises(sqlite3.OperationalError):
        drafts.add_source(store, order_id, "Reviewer", "T", "Read the mass.")


def test_demo_answers_are_not_captured(store):
    order_id = procedure_demo.start(store, "Reviewer")
    drafts.add_source(store, order_id, "Reviewer", "ignored", "ignored")
    assert rows(store) == [0, 0, 0]


def test_first_draft_answer_accepts_a_source_id(store):
    data = {"request_id": "archive-1", "lab": {"id": "records", "name": "Records", "instruments": [], "documents": []},
            "experiment": {"id": "trace", "lab_id": "records", "title": "Trace review", "goal": "Compare drift plots.",
                           "instrument_ids": [], "documents": []}}
    start = first_draft.start(store, "Ada", data)
    order_id = start["order"]["id"]
    with pytest.raises(ContextError):
        first_draft.answer(store, "Reviewer", order_id, {"title": "T", "text": "x", "method_id": "m"})
    result = first_draft.answer(store, "Reviewer", order_id, {
        "title": "T", "text": "Compare the drift plots.\nLog the trace IDs.", "source_id": CATALOG,
        "request_id": "r1"})
    assert result["state"] == "in_review"
    (entry,) = library.latest(store, "records")
    assert entry["source_id"] == CATALOG


def automatic(store):
    data = {"request_id": "a-1", "lab": {"id": "records", "name": "Records", "instruments": [], "documents": []},
            "experiment": {"id": "trace", "lab_id": "records", "title": "Trace review", "goal": "Compare drift plots.",
                           "instrument_ids": [], "documents": []}}
    return first_draft.start(store, "Ada", data)["order"]["id"]


def test_detail_suggested_sources(store):
    order_id = automatic(store)
    assert first_draft.detail(store, order_id)["suggested_sources"] == []
    findings = [{"id": "a", "title": "A", "locator": "p1", "document_id": "library:a"},
                {"id": "b", "title": "B", "locator": "p2", "kind": "manual"}]
    briefing.save(store, order_id, {"reference_library": {"findings": findings}})
    assert first_draft.detail(store, order_id)["suggested_sources"] == [
        {"id": "b", "title": "B", "locator": "p2"}]


def portal_order(uvvis_lab_dict, b12_experiment_dict):
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        return asking_order(store, uvvis_lab_dict, b12_experiment_dict)[0]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from labfactory.hosted_auth import password_hash, token_digest
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "portal.sqlite"))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "test-session-secret-with-at-least-32-characters")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Ada": password_hash(PASSWORD)}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"spectrometer-agent": token_digest(AGENT_TOKEN)}))
    with TestClient(application, base_url=ORIGIN, headers={"Origin": ORIGIN}) as session:
        session.post("/api/login", json={"name": "Ada", "password": PASSWORD}).raise_for_status()
        yield session


def library_rows():
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        return rows(store)


def test_source_route_forwards_source_id(client, uvvis_lab_dict, b12_experiment_dict):
    order_id = portal_order(uvvis_lab_dict, b12_experiment_dict)
    bad = client.post(f"/api/procedures/{order_id}/source",
                      json={"title": "T", "text": "Read the mass.", "source_id": "nope"})
    assert bad.status_code == 400
    res = client.post(f"/api/procedures/{order_id}/source",
                      json={"title": "T", "text": "Read the mass.", "source_id": CATALOG})
    assert res.status_code == 201
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        assert [e["source_id"] for e in library.latest(store, uvvis_lab_dict["id"])] == [CATALOG]


@pytest.mark.parametrize("title,text", [("t" * 251, "Read the mass."),
                                        ("T", "x" * (library.MAX_TEXT_BYTES + 1))])
def test_skipped_capture_does_not_roll_back_the_answer(client, uvvis_lab_dict, b12_experiment_dict, title, text):
    order_id = portal_order(uvvis_lab_dict, b12_experiment_dict)
    res = client.post(f"/api/procedures/{order_id}/source", json={"title": title, "text": text})
    assert res.status_code == 201
    assert client.get(f"/api/orders/{res.json()['id']}").status_code == 200
    assert library_rows() == [0, 0, 0]


def test_two_attributed_answers_keep_both_passages(store, asked):
    order_id, lab_id = asked
    library.add(store, "Ada", "Full manual text.", source_id=CATALOG)
    first = drafts.add_source(store, order_id, "Reviewer", "T", "Passage A.", source_id=CATALOG)
    AgentTools(store).claim_work_order(first, "worker")
    AgentTools(store).submit_artifact(first, "worker", QUESTION)
    drafts.add_source(store, first, "Reviewer", "T", "Passage B.", source_id=CATALOG)
    entry = library.visible(store, lab_id)[CATALOG]
    text = library.get(store, entry["id"])["text"]
    assert entry["scope"] == library.lab_scope(lab_id) and entry["revision"] == 2
    assert text == "Full manual text.\n\nPassage A.\n\nPassage B."


def test_two_answers_with_the_same_title_keep_both_passages(store, asked):
    order_id, lab_id = asked
    first = drafts.add_source(store, order_id, "Reviewer", "Balance worksheet", "Passage A.")
    AgentTools(store).claim_work_order(first, "worker")
    AgentTools(store).submit_artifact(first, "worker", QUESTION)
    drafts.add_source(store, first, "Reviewer", "balance worksheet", "Passage B.")
    (entry,) = library.latest(store, lab_id)
    assert entry["revision"] == 2
    assert library.get(store, entry["id"])["text"] == "Passage A.\n\nPassage B."
