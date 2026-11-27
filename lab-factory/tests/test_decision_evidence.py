import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from labfactory import decision_evidence, source_drafter
from labfactory.hosted import application
from labfactory.store import Store
from labfactory.workorders import WorkOrders


PATH = "/api/procedure-drafts"
FIXTURE = Path(__file__).parent / "fixtures" / "procedure_drafts" / "filters.json"


@pytest.mark.parametrize("outcome", ["resolved", "researcher_choice", "missing_method_detail", "bad_quote",
                                     "irrelevant_search", "late_question", "failed_decision_review"])
def test_decision_retrieval_and_gates(tmp_path, monkeypatch, outcome):
    body = json.loads(FIXTURE.read_text())
    docs = body["lab"]["documents"]
    # More passages with the exact goal than fit in the old goal-only retrieval.
    docs.insert(0, {"id": "noise", "kind": "note", "title": "Historical goals", "source": "archive",
                    "text": "\n".join([body["experiment"]["goal"]] * 75)})
    docs.append({"id": "channel", "kind": "note", "title": "Session designation", "source": "bench",
                 "text": "The designated calibrated channel for this series is 520 nm."})
    query = "designated calibrated channel session designation"
    quote = docs[-1]["text"]
    bad = outcome == "bad_quote"
    evidence = {"document": "channel", "passage": 1, "quote": "invented text" if bad else quote}
    draft_calls = []
    def ask(prompt, data, schema, timeout):
        if "searches" in schema["properties"]:
            assert len(data["catalog"]) == 5 and "passages" not in data
            return {"searches": (["spare equipment"] if outcome == "irrelevant_search" else []) + [query]}
        if "decisions" in schema["properties"]:
            if "proposed" in data:
                if outcome in ("irrelevant_search", "late_question"):
                    return {"decisions": [{**data["proposed"][0], "status": "out_of_scope", "question": "",
                                           "goal_quote": "", "evidence": [],
                                           "finding": "Spare equipment is outside this comparison."}]}
                return {"decisions": data["proposed"]}
            assert ["channel", 1] in data["searches"][-1]["hits"]
            assert len(data["passages"]) <= 12 * len(data["searches"])
            noise = [{"index": 1, "status": "researcher_choice", "finding": "Possible extra setup.",
                      "goal_quote": "", "evidence": [], "question": "Use the spare equipment?"}]
            return {"decisions": (noise if outcome == "irrelevant_search" else []) + [{
                                   "index": len(data["searches"]), "status": outcome if outcome in decision_evidence.GAPS else "resolved",
                                   "finding": "Designated wavelength", "goal_quote": "", "evidence": [evidence],
                                   "question": "Which source or choice applies?" if outcome in decision_evidence.GAPS else ""}]}
        # Simulate a procedure with the signed comparison reversed on its first submission.
        text = data["draft"]["steps"][0]["text"]
        return {"review": [{"index": data["indices"][0], "steps": [1], "passed": outcome != "failed_decision_review" and "A minus B" in text,
                            "reason": "Report A minus B."}]}

    def author(context, feedback):
        assert [p["document"] for p in context["passages"]] == ["channel"]
        draft_calls.append(feedback)
        if outcome == "late_question" and not feedback:
            return {"needs_input": "Use the spare equipment?", "question_kind": "researcher_choice"}
        if feedback:
            expected = "Spare equipment" if outcome == "late_question" else "Report A minus B"
            assert any(expected in p for p in feedback["failures"])
        return {"steps": [{"text": "Report A minus B." if feedback else "Report B minus A.",
                           "citations": ["channel"], "evidence": [evidence],
                           "action": {"instrument_id": "photometer-1", "command": "read_transmittance",
                                      "settings": [{"parameter": "wavelength", "value": 520, "unit": "nm"}]}}]}
    db = str(tmp_path/"test.sqlite")
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", db)
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.setenv("LABFACTORY_AGENTS", "{}")
    monkeypatch.setattr(decision_evidence, "ask", ask)
    monkeypatch.setattr(source_drafter, "generate", author)
    with TestClient(application, base_url="http://localhost", headers={"Origin": "http://localhost"}) as api:
        response = api.post(PATH, json=body)
        result = response.json()
        if bad:
            assert response.status_code == 201 and not draft_calls
            assert result["state"] == "needs_input" and result["input_kind"] == "missing_method_detail"
            assert "wavelength (nm)" in result["question"] and "method passage" in result["question"]
            assert set(result["submission"]["artifact"]) == {"needs_input"}
            assert "invented text" not in json.dumps(result)
            assert result == api.post(PATH, json=body).json()
            return
        assert response.status_code == 201 and result == api.post(PATH, json=body).json()
        assert any(d["search"] == query for d in result["decision_evidence"])
        if outcome == "failed_decision_review":
            assert len(draft_calls) == 2 and result["state"] == "needs_input"
            assert set(result["submission"]["artifact"]) == {"needs_input"} and not result["submission"]["passed"]
            return
        if outcome == "irrelevant_search":
            assert result["decision_evidence"][0]["status"] == "out_of_scope"
        if outcome in decision_evidence.GAPS:
            assert result["state"] == "needs_input" and result["input_kind"] == outcome
            assert set(result["submission"]["artifact"]) == {"needs_input"} and not draft_calls
            return
        assert result["state"] == "in_review" and len(draft_calls) == 2
        assert all(c["passed"] for c in result["submission"]["results"])
        with Store(db) as store:
            orders = WorkOrders(store)
            order = orders.get(result["order"]["id"])
            assert all(c.passed for c in orders._check(order, result["submission"]["artifact"]))
            result["submission"]["artifact"]["steps"][0]["text"] = "Report B minus A."
            assert any(not c.passed for c in orders._check(order, result["submission"]["artifact"]))


def test_model_manual_on_instrument_step():
    bench = {"document": "field", "passage": 1, "quote": "Current field verification."}
    manual = {"document": "guide", "passage": 3, "quote": "Integration period controls the measurement cycle."}
    plan = [{"index": 1, "status": "resolved", "search": "operation", "evidence": [bench, manual],
             "instrument_manuals": [{**manual, "instrument": "meter"}]}]
    reviewed = [{"index": 1, "steps": [1, 2], "passed": True, "reason": "Cycle is correctly specified."}]
    artifact = {"steps": [{"action": None, "evidence": [manual]}, {"action": {"instrument_id": "meter"},
                                                                    "evidence": [bench]}]}
    failed, = decision_evidence.checks(artifact, plan, reviewed)
    assert not failed.passed and "guide, passage 3" in failed.detail
    artifact["steps"][1]["evidence"].append(manual)
    assert all(c.passed for c in decision_evidence.checks(artifact, plan, reviewed))


@pytest.mark.parametrize("failure_stage", ["planning", "late_question", "outage"])
def test_verification_recovery_can_be_answered(tmp_path, monkeypatch, failure_stage):
    body = json.loads(FIXTURE.read_text())
    db = str(tmp_path/"recovery.sqlite")
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", db)
    monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    monkeypatch.setenv("LABFACTORY_AGENTS", "{}")

    def prepare(lab, experiment, context, timeout):
        answer_id = context["answer_document_id"]
        if failure_stage == "outage":
            raise RuntimeError("Worker unavailable")
        if not answer_id and failure_stage == "planning":
            raise decision_evidence.InvalidDecision("Unverified evidence in decision assessment")
        d = experiment.documents[-1]
        return [{"index": 1, "search": "study wavelength", "status": "resolved", "question": "",
                 "goal_quote": "", "finding": d.text,
                 "hits": [[d.id, 1]], "evidence": [{"document": d.id, "passage": 1, "quote": d.text}],
                 "instrument_manuals": []}]

    def author(context, feedback):
        if not context["answer_document_id"]:
            return {"needs_input": "Does the retired setting apply?", "question_kind": "missing_method_detail"}
        ref, = context["decisions"][0]["evidence"]
        return {"steps": [{"text": "Measure each filter at the selected channel.", "citations": [ref["document"]],
                           "evidence": [ref], "action": {"instrument_id": "photometer-1", "command": "read_transmittance",
                                                        "settings": [{"parameter": "wavelength", "value": 520, "unit": "nm"}]}}]}

    def late(*args):
        raise decision_evidence.InvalidDecision("Unverified goal excerpt")

    monkeypatch.setattr(decision_evidence, "prepare", prepare)
    monkeypatch.setattr(decision_evidence, "assess_late_question", late)
    monkeypatch.setattr(source_drafter, "generate", author)
    monkeypatch.setattr(decision_evidence, "review", lambda *_: [
        {"index": 1, "steps": [1], "passed": True, "reason": "Uses the prescribed channel."}])
    with TestClient(application, base_url="http://localhost", headers={"Origin": "http://localhost"}) as api:
        res = api.post(PATH, json=body)
        start = res.json()
        if failure_stage == "outage":
            assert res.status_code == 503 and start["state"] == "drafting"
            assert api.get(PATH+"/"+start["order_id"]).json()["submission"] is None
            return
        assert res.status_code == 201 and start["state"] == "needs_input"
        assert start["input_kind"] == "missing_method_detail" and "wavelength (nm)" in start["question"]
        assert "retired" not in start["question"] and "520" not in start["question"]
        assert start == api.post(PATH, json=body).json()
        assert not start["submission"]["passed"] and set(start["submission"]["artifact"]) == {"needs_input"}
        parent = start["order"]["id"]
        answer = {"request_id": "addendum", "title": "Approved study channel", "text": "Use 520 nm."}
        url = f"{PATH}/{parent}/answers"
        response = api.post(url, json=answer)
        final = response.json()
        assert response.status_code == 201 and final["state"] == "in_review" and final["previous_order"] == parent
        assert final["submission"]["passed"] and final == api.post(url, json=answer).json()
