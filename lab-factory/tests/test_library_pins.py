from dataclasses import replace

import pytest

from labfactory import library, procedure_drafts as drafts
from labfactory.agent import AgentTools
from labfactory.artifacts import parse_artifact
from labfactory.citations import CitationIndex
from labfactory.context import Document, experiment_from_dict, lab_from_dict
from labfactory.workorders import WorkOrders

CARY = "agilent-cary-60-user-guide"
HONEY = "ihc-2009-honey-moisture"
TEXT = "Set the wavelength to 550 nm.\nZero with the blank."
OWN = {"id": "own", "kind": "note", "title": "Own note", "source": "operator", "text": "Own text."}


@pytest.fixture
def setup(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    b12_experiment_dict["documents"] = [OWN]
    exp = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(exp)
    return exp


def order_for(store, exp, *entries):
    order = drafts.create(store, exp.id, "Reviewer")
    if entries:
        library.pin(store, order.id, list(entries))
    return order


def test_pinned_entries_appear_before_the_experiments_own_documents(store, setup):
    entry = library.add(store, "Ana", TEXT, source_id=CARY)
    order = order_for(store, setup, entry)
    digest = store.get_experiment(setup.id)[1].digest
    docs = WorkOrders(store).pinned_context(order.id)[1].documents
    assert [d.id for d in docs] == ["library:" + CARY, "own"]
    assert (docs[0].kind, docs[0].title, docs[0].source, docs[0].text) == (
        entry["kind"], entry["title"], entry["origin"], TEXT)
    stored, revision = store.get_experiment(setup.id)
    assert [d.id for d in stored.documents] == ["own"] and revision.digest == digest


def test_order_without_pins_is_unchanged(store, setup):
    order = order_for(store, setup)
    lab, exp = WorkOrders(store).pinned_context(order.id)
    assert lab == store.get_lab(order.lab_id, order.lab_revision)[0]
    assert exp == store.get_experiment(order.experiment_id, order.experiment_revision)[0]


def test_pinned_text_is_unchanged_after_the_source_is_revised(store, setup):
    first = library.add(store, "Ana", TEXT, source_id=CARY)
    order = order_for(store, setup, first)
    second = library.add(store, "Ana", "Different text.", source_id=CARY)
    library.share(store, "Ana", second["id"])
    docs = WorkOrders(store).pinned_context(order.id)[1].documents
    assert docs[0].text == TEXT
    assert library.pinned(store, order.id)[0]["revision"] == 1


def test_pinned_document_can_be_cited_and_quoted(store, setup):
    entry = library.add(store, "Ana", TEXT, source_id=CARY)
    order = order_for(store, setup, entry)
    lab, exp = WorkOrders(store).pinned_context(order.id)
    doc = "library:" + CARY
    quote = "Set the wavelength to 550 nm."
    artifact = parse_artifact("procedure", {"steps": [
        {"text": "Set the wavelength.", "citations": [doc],
         "evidence": [{"document": doc, "passage": 1, "quote": quote}]}]})
    assert all(r.passed for r in drafts.evidence_checks(artifact, lab, exp, required=True))
    assert any(p["document"] == doc for p in drafts.passages(lab, exp))
    context = AgentTools(store).get_work_order_context(order.id, "wavelength 550")
    assert doc in [d["id"] for d in context["experiment"]["documents"]]
    assert any(p["document"] == doc for p in context["passages"])


def test_colliding_document_id_is_skipped(store, setup):
    entry = library.add(store, "Ana", TEXT, source_id=CARY)
    own = Document("library:" + CARY, "note", "Mine", "operator", "Mine.")
    store.put_experiment(replace(setup, documents=(own,)))
    order = order_for(store, store.get_experiment(setup.id)[0], entry)
    lab, exp = WorkOrders(store).pinned_context(order.id)
    assert [d.id for d in exp.documents] == ["library:" + CARY]
    assert exp.documents[0].text == "Mine."
    CitationIndex(lab, exp).resolve("library:" + CARY)


def test_pin_is_capped_deduplicated_and_ordered(store, setup):
    entries = [library.add(store, "Ana", f"Text {i}.", title=f"Source {i}") for i in range(10)]
    private = library.add(store, "Ana", "Private.", title="Private", lab_id=setup.lab_id)
    order = order_for(store, setup, *entries)
    pins = library.pinned(store, order.id)
    assert [p["document_id"] for p in pins] == [e["document_id"] for e in entries[:8]]
    assert len(library.pin(store, order.id, [entries[0]])) == 8
    other = order_for(store, setup, private, entries[0])
    pins = library.pinned(store, other.id)
    assert [(p["scope"], p["title"]) for p in pins] == [("lab", "Private"), ("shared", "Source 0")]
    assert set(pins[0]) == {"document_id", "source_id", "title", "scope", "entry_id", "revision"}


def test_follow_up_order_keeps_its_pins(store, setup):
    first = order_for(store, setup, library.add(store, "Ana", TEXT, source_id=CARY),
                      library.add(store, "Ana", "Honey.", source_id=HONEY))
    second = drafts.create(store, setup.id, "Reviewer", previous=first.id)
    assert library.pinned(store, second.id) == library.pinned(store, first.id) != []


def test_answer_document_is_still_last_when_library_documents_are_pinned(store, setup):
    order = order_for(store, setup, library.add(store, "Ana", TEXT, source_id=CARY))
    orders = WorkOrders(store)
    orders.claim(order.id, "agent")
    orders.submit(order.id, "agent", {"needs_input": "Which mass?"})
    new = drafts.add_source(store, order.id, "Reviewer", "Method note", "Read the mass.")
    docs = orders.pinned_context(new)[1].documents
    assert docs[-1].title == "Method note" and docs[0].id == "library:" + CARY
    assert not any(d.id.startswith("library:") for d in store.get_experiment(setup.id)[0].documents)
