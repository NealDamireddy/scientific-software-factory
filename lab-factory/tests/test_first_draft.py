from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from labfactory import first_draft
from labfactory.context import ContextError
from labfactory.store import Store
from labfactory.workorders import WorkOrderError, WorkOrders


@pytest.fixture
def intake(uvvis_lab_dict):
    return {"request_id": "probe-1", "lab": uvvis_lab_dict, "experiment": {
        "id": "reference-scan", "lab_id": uvvis_lab_dict["id"], "title": "Reference scan",
        "goal": "Inspect the reference card and read its absorbance.",
        "instrument_ids": ["uvvis-1"], "documents": [{"id": "scan-sop", "title": "Reference card scan",
        "source": "Training manual §2", "kind": "sop",
        "text": "1. Inspect the reference card.\n2. Read absorbance at 550 nm.\n3. Log the displayed reading."}]}}


def test_context_to_first_draft_and_review(store, intake):
    result = first_draft.start(store, "Reviewer", intake)
    assert (result["state"], result["question"], result["submission"]["number"]) == ("in_review", None, 1)
    assert [s["passage"] for s in result["sources"]] == [1, 2, 3]
    steps = result["submission"]["artifact"]["steps"]
    assert steps[1]["action"]["settings"] == [{"parameter": "wavelength", "value": 550, "unit": "nm"}]
    assert steps[0]["text"] == "Inspect the reference card."
    id = result["order"]["id"]
    WorkOrders(store).approve(id, "Reviewer", 1)
    assert first_draft.detail(store, id)["state"] == "released"
    assert first_draft.start(store, "Reviewer", intake)["order"]["id"] == id
    another = first_draft.start(store, "Reviewer", {"request_id": "second", "experiment_id": "reference-scan"})
    assert another["submission"]["artifact_digest"] == result["submission"]["artifact_digest"]


def test_question_to_new_checked_revision_preserves_unaffected_steps_and_evidence(store, intake):
    method = intake["experiment"]["documents"][0]
    method["text"] = method["text"].replace(" at 550 nm", "")
    result = first_draft.start(store, "Reviewer", intake)
    id = result["order"]["id"]
    assert (result["state"], result["question_step"]) == ("needs_input", 2)
    assert "wavelength" in result["question"]
    with pytest.raises(WorkOrderError):
        WorkOrders(store).approve(id, "Reviewer", 1)
    answer = {"request_id": "reply", "title": "Method addendum", "text": "The wavelength is 550 nm."}
    corrected = first_draft.answer(store, "Reviewer", id, answer)
    new_id = corrected["order"]["id"]
    assert corrected["state"] == "in_review"
    steps = corrected["submission"]["artifact"]["steps"]
    assert len(steps) == 3 and len(steps[1]["citations"]) == 2
    assert steps[1]["action"]["settings"][0]["value"] == 550
    assert corrected["order"]["experiment_revision"] == 2
    original = first_draft.detail(store, id)
    assert original["state"] == "superseded" and original["next_order"] == new_id
    assert first_draft.answer(store, "Reviewer", id, answer)["order"]["id"] == new_id
    with pytest.raises(WorkOrderError):
        first_draft.answer(store, "Reviewer", id, {**answer, "text": "555 nm"})
    with pytest.raises(WorkOrderError):
        first_draft.answer(store, "Reviewer", id, {**answer, "request_id": "new"})
    assert len(WorkOrders(store).list()) == 2


def test_no_b12_assumption_or_worker_for_document_only_experiments(store):
    data = {"request_id": "archive-1", "lab": {"id": "records", "name": "Records", "instruments": [], "documents": []},
            "experiment": {"id": "trace", "lab_id": "records", "title": "Trace review", "goal": "Compare drift plots.",
                           "instrument_ids": [], "documents": []}}
    start = first_draft.start(store, "Ada", data)
    assert start["state"] == "needs_input" and "Compare drift plots" in start["question"]
    answer = first_draft.answer(store, "Ada", start["order"]["id"], {
        "request_id": "archive-2", "title": "Archive method", "text": "Compare the drift plots.\nLog the trace IDs."})
    assert answer["state"] == "in_review" and len(answer["sources"]) == 2


def test_out_of_range_and_ambiguous_methods(store, intake):
    intake["experiment"]["documents"].append({**intake["experiment"]["documents"][0], "id": "other"})
    res = first_draft.start(store, "Ada", intake)
    assert res["state"] == "needs_input" and "Which method" in res["question"]
    use = first_draft.answer(store, "Ada", res["order"]["id"], {"request_id": "choose", "method_id": "other"})
    assert use["state"] == "in_review"
    fresh = deepcopy(intake)
    fresh["request_id"] = "range"
    fresh["method_id"] = "other"
    fresh["experiment"]["id"] = "scan-2"
    fresh["experiment"]["documents"][1]["text"] = "Read absorbance at 950 nm."
    res = first_draft.start(store, "Ada", fresh)
    assert "outside" in res["question"] and res["question_step"] == 1


def test_atomic_intake_and_mismatched_retry(store, intake):
    wrong = deepcopy(intake)
    wrong["experiment"]["instrument_ids"] = ["unknown"]
    with pytest.raises(ContextError):
        first_draft.start(store, "Ada", wrong)
    assert store.connection.execute("select count(*) from records").fetchone()[0] == 0
    first_draft.start(store, "Ada", intake)
    wrong = deepcopy(intake)
    wrong["experiment"]["goal"] = "different"
    with pytest.raises(WorkOrderError, match="different input"):
        first_draft.start(store, "Ada", wrong)
    with pytest.raises(WorkOrderError, match="different content"):
        first_draft.start(store, "Ada", {**wrong, "request_id": "another"})
    assert len(WorkOrders(store).list()) == 1


def test_competing_first_draft_retries(tmp_path, intake):
    path = tmp_path / "concurrent.db"
    with Store(path):
        pass
    def run(_):
        with Store(path) as store:
            return first_draft.start(store, "user", intake)["order"]["id"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert len(set(pool.map(run, range(3)))) == 1
    with Store(path) as store:
        assert len(WorkOrders(store).list()) == 1


def test_stale_context_conflicts_before_saving_reply(store, intake):
    from dataclasses import replace
    result = first_draft.start(store, "Ada", {**intake, "method_id": "missing"})
    lab, _ = store.get_lab(intake["lab"]["id"])
    store.put_lab(replace(lab, name="Revised lab"))
    with pytest.raises(WorkOrderError, match="context has changed"):
        first_draft.answer(store, "Ada", result["order"]["id"],
                           {"request_id": "answer", "title": "Method update", "text": "Log the reading."})
    assert len(WorkOrders(store).list()) == 1
    assert store.get_experiment(intake["experiment"]["id"])[1].number == 1


def test_hand_amount_is_separate_and_cited(store, intake):
    intake["experiment"]["documents"][0]["text"] = "Measure 2.5 mL of reference water."
    result = first_draft.start(store, "Ada", intake)
    assert result["state"] == "in_review"
    step, = result["submission"]["artifact"]["steps"]
    assert step["amounts"] == [{"what": "reference water", "value": 2.5, "unit": "mL"}]
    assert step["evidence"][0]["quote"] == "Measure 2.5 mL of reference water."
    assert "mL" not in step["text"]


def test_ambiguous_or_conditional_setting_asks_for_source(store, intake):
    intake["experiment"]["documents"][0]["text"] = "Read absorbance at 550 nm only if the reference is clear."
    res = first_draft.start(store, "Ada", intake)
    assert res["state"] == "needs_input" and res["question_step"] == 1
    assert res["sources"][0]["text"].endswith("if the reference is clear.")
