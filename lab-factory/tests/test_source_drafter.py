from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Event

import pytest
from starlette.testclient import TestClient

from labfactory.artifacts import parse_artifact
from labfactory.store import Store
from labfactory.workorders import WorkOrders
from labfactory import source_drafter
from labfactory.procedure_drafts import passages
from labfactory.hosted import application


FIXTURES = Path(__file__).parent / "fixtures" / "procedure_drafts"
PATH = "/api/procedure-drafts"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "walkthrough.sqlite"))
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.setenv("LABFACTORY_AGENTS", "{}")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    # These tests isolate the author, leases and paper checker. The decision
    # retrieval and independent review have their own endpoint tests.
    def prepare(lab, exp, context, timeout):
        refs = [{"document": p["document"], "passage": p["passage"], "quote": p["text"]}
                for p in passages(lab, exp)]
        return [{"index": 1, "search": "study design", "finding": "Use the supplied study design.",
                 "status": "resolved", "question": "", "goal_quote": "", "hits": [], "evidence": refs}]
    monkeypatch.setattr(source_drafter.decision_evidence, "prepare", prepare)
    monkeypatch.setattr(source_drafter.decision_evidence, "review", lambda *_: [
        {"index": 1, "steps": [1], "passed": True, "reason": "Implements the study decision."}])
    with TestClient(application, base_url="http://localhost", headers={"Origin": "http://localhost"}) as client:
        yield client


def _input(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def _step(context, documents, text):
    selected = [p for p in context["passages"] if p["document"] in documents]
    return {"text": text, "citations": list(dict.fromkeys(p["document"] for p in selected)),
            "evidence": [{"document": p["document"], "passage": p["passage"], "quote": p["text"]} for p in selected]}


@pytest.mark.parametrize("name", ["exoplanets", "filters"])
def test_goal_sources_question_answer_and_verification(api, monkeypatch, name):
    calls = []
    def author(context, feedback):
        calls.append((context, feedback))
        answer_id = context["answer_document_id"]
        if not answer_id:
            return {"needs_input": "Which discovery population?" if name == "exoplanets" else "Which wavelength?"}
        assert context["prior_question"] and context["passages"][0]["document"] == answer_id
        if name == "exoplanets":
            return {"steps": [_step(context, ["dictionary", "study", answer_id], "Compare distinct planet counts by discovery year.")]}
        step = _step(context, ["photometer-guide", "channel-record", answer_id], "Measure each identified filter.")
        step["action"] = {"instrument_id": "photometer-1", "command": "read_transmittance",
                          "settings": [{"parameter": "wavelength", "value": 520 if feedback else 900, "unit": "nm"}]}
        return {"steps": [step]}

    monkeypatch.setattr(source_drafter, "generate", author)
    request = _input(name)
    response = api.post(PATH, json=request)
    assert response.status_code == 201
    start = response.json()
    order_id = start["order"]["id"]
    assert start["state"] == "needs_input" and start["submission"]["worker"] == source_drafter.WORKER
    assert api.post(PATH, json=request).json() == start and len(calls) == 1
    answer = {"request_id": "reply", "title": "Decision", "text": "Use 520 nm." if name == "filters" else "Transit discoveries only."}
    path = f"{PATH}/{order_id}/answers"
    final = api.post(path, json=answer).json()
    assert final["state"] == "in_review" and final["submission"]["number"] == 1
    assert all(r["passed"] for r in final["submission"]["results"])
    assert final["previous_order"] == order_id and final["order"]["experiment_revision"] == 2
    assert api.get(f"{PATH}/{order_id}").json()["next_order"] == final["order"]["id"]
    assert api.post(path, json=answer).json() == final
    assert len(calls) == (3 if name == "filters" else 2)
    if name == "filters":
        assert "outside" in str(calls[-1][1]["failures"])


def test_interrupted_model_call_retries_same_job_and_never_persists_invalid_draft(api, monkeypatch):
    request = _input("exoplanets")
    monkeypatch.setattr(source_drafter, "generate", lambda *_: {"steps": []})
    first = api.post(PATH, json=request)
    assert first.status_code == 503
    order_id = first.json()["order_id"]
    pending = api.get(f"{PATH}/{order_id}").json()
    assert pending["state"] == "drafting" and pending["submission"] is None
    monkeypatch.setattr(source_drafter, "generate", lambda *_: {"needs_input": "Which cohort?"})
    second = api.post(PATH, json=request).json()
    assert second["order"]["id"] == order_id and second["question"] == "Which cohort?"


def test_overlapping_replays_share_one_author_and_do_not_hold_write_lock(api, monkeypatch):
    entered, proceed = Event(), Event()
    def author(*_):
        entered.set()
        assert proceed.wait(8)
        return {"needs_input": "Which discovery cohort?"}
    monkeypatch.setattr(source_drafter, "generate", author)
    request = _input("exoplanets")
    with ThreadPoolExecutor(max_workers=1) as pool:
        original = pool.submit(api.post, PATH, json=request)
        try:
            assert entered.wait(5)
            duplicate = api.post(PATH, json=request)
            assert duplicate.status_code == 202 and duplicate.json()["state"] == "drafting"
        finally:
            proceed.set()
        assert original.result().json()["state"] == "needs_input"


def test_paper_omission_triggers_automatic_correction(api, monkeypatch):
    request = _input("grapes")
    unrelated = {"id": "other", "kind": "paper", "title": "Soil survey",
                 "source": "field notes", "text": "Soil cores were taken from vineyard plots."}
    request["lab"]["documents"].append(unrelated)
    paper = "berry-paper"
    quote = "The individual berry was the sampling unit in this part of the study."
    reviews = [{"document": paper, "reason": "The selected design uses individual berries.",
                "claims": [{"step": 1, "passage": 1, "quote": quote, "choice": "Individual berry sampling unit"}]},
               {"document": "other", "reason": "This procedure does not sample soil.", "claims": []}]
    draft_calls = []
    def author(context, feedback):
        if not context["answer_document_id"]:
            return {"needs_input": "Use individual specimens or composites?"}
        draft_calls.append(feedback)
        return json.loads(json.dumps(_input("grape_missing_citation")).replace(
            "__decision__", context["answer_document_id"]))
    monkeypatch.setattr(source_drafter, "generate", author)
    monkeypatch.setattr(source_drafter.paper_review, "review", lambda *_: reviews)
    start = api.post(PATH, json=request).json()
    answer = {"request_id": "reply", "title": "Decision",
              "text": "Use the six individual berry-juice specimens from each lot and compare the two lot means. "
                      "The composites are outside this comparison."}
    path = f"{PATH}/{start['order']['id']}/answers"
    final = api.post(path, json=answer).json()
    assert final["state"] == "in_review" and final["submission"]["number"] == 1
    assert draft_calls == [None]
    assert final == api.post(path, json=answer).json()
    with Store(os.environ["LABFACTORY_LOCAL_DB"]) as store:
        orders = WorkOrders(store)
        order = orders.get(final["order"]["id"])
        row = store.connection.execute("SELECT corrections FROM procedure_paper_reviews WHERE work_order_id=?",
                                       (order.id,)).fetchone()
        failures = json.loads(row["corrections"])
        assert len(failures) == 1 and len(failures[0]) == 1
        assert "berry-paper, step 1" in failures[0][0] and quote in failures[0][0]
        artifact = final["submission"]["artifact"]
        checks = orders._check(order, artifact)
        assert all(c.passed for c in checks)
        lab, exp = orders.pinned_context(order.id)
        # A valid quote on the zeroing step, or an irrelevant quote from the correct
        # paper on the sampling step, must leave the sampling claim unresolved.
        sampling, zero = artifact["steps"][:2]
        evidence = sampling["evidence"].pop()
        zero["citations"].append(paper)
        zero["evidence"].append(evidence)
        sampling["evidence"].append(dict(evidence, quote="The water-zeroed refractometer was cleaned and dried for each new reading."))
        checks = source_drafter.paper_review.coverage_checks(parse_artifact("procedure", artifact), lab, exp, reviews)
        assert [c.name for c in checks if not c.passed] == ["published method: berry-paper, step 1"]
        assert any(not c.passed for c in orders._check(order, artifact))
        assert not all(c.passed for c in source_drafter.paper_review.coverage_checks(
            parse_artifact("procedure", artifact), lab, exp, reviews[:1]))


def test_paper_review_failure_leaves_no_verified_submission(api, monkeypatch):
    request = _input("grapes")
    def author(context, _feedback):
        if not context["answer_document_id"]:
            return {"needs_input": "Individual berries or composite juice?"}
        step = _step(context, ["bench-record", "hanna-manual", context["answer_document_id"]],
                     "Measure the juice of each individual berry.")
        step["action"] = {"instrument_id": "brix-1", "command": "read_brix", "settings": []}
        return {"steps": [step]}

    def unavailable(*_):
        raise RuntimeError("review unavailable")

    monkeypatch.setattr(source_drafter, "generate", author)
    monkeypatch.setattr(source_drafter.paper_review, "review", unavailable)
    start = api.post(PATH, json=request).json()
    path = f"{PATH}/{start['order']['id']}/answers"
    answer = {"title": "Decision", "request_id": "reply", "text": "Six individual berries per lot; compare the two means"}
    failed = api.post(path, json=answer)
    assert failed.status_code == 503
    pending = api.get(f"{PATH}/{failed.json()['order_id']}").json()
    assert pending["state"] == "drafting" and pending["submission"] is None

    # Retrying with a reviewer that omits the paper must also fail closed.
    monkeypatch.setattr(source_drafter.paper_review, "review", lambda *_: [])
    retry = api.post(path, json=answer)
    assert retry.status_code == 503 and retry.json()["order_id"] == pending["order"]["id"]
    assert api.get(f"{PATH}/{pending['order']['id']}").json()["submission"] is None
