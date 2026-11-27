import hashlib
import json
from uuid import uuid4

import pytest

from labfactory import analysis_requests as drift_plots
from labfactory.agent import AgentTools
from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.workorders import WorkOrderError


def request(project="stage-example"):
    return {"objective": "Overlay stage drift from my runs.", "project": project, "request_id": str(uuid4())}


def recipe(**changes):
    return {"filename": "*", "context_number": 1, "origin_mm": 2, "reading_unit": "mm", "ticks_per_mm": 1,
            "reading_column": "position", "role_column": "", "role_value": "", "timestamp_column": "time",
            "timestamp_unit": "ms", "interval_seconds": 0, **changes}


def test_question_answer_retry_and_finished_app(store):
    data = request()
    result = drift_plots.create(store, "Researcher", data)
    key = result["id"]
    agent = AgentTools(store)
    assert drift_plots.create(store, "Researcher", data) == result
    with pytest.raises(WorkOrderError):
        drift_plots.create(store, "Researcher", {**data, "objective": "A different request"})
    assert agent.list_work_orders("open")[0]["id"] == key
    assert agent.claim_work_order(key, "A")["status"] == "in_progress"
    assert "error" in agent.claim_work_order(key, "B")
    question = {"turn": 1, "plot": {"question": "Which configuration and timing apply?", "summary": "Four snapshots.",
                                    "axis": "pending", "runs": []}}
    assert "error" in agent.submit_artifact(key, "B", question, 1)
    assert agent.submit_artifact(key, "A", question, 1)["status"] == "needs_input"
    with pytest.raises(WorkOrderError):
        drift_plots.download(store, key)
    answer = {"turn": 1, "answer": "Snapshot 1, all rows in every file. Elapsed time from time in ms."}
    for _ in range(2):
        assert drift_plots.answer(store, key, "Researcher", answer) == result
    with pytest.raises(WorkOrderError):
        drift_plots.answer(store, key, "Researcher", {**answer, "answer": "Use row order."})
    ctx = agent.get_work_order_context(key)["drift_plot"]
    assert ctx["history"][0]["answer"] == answer["answer"] and ctx["turn"] == 2
    assert agent.claim_work_order(key, "B")["status"] == "in_progress"
    ready = {"axis": "elapsed", "summary": "Use snapshot 1 and the confirmed timestamp.", "question": "", "runs": [recipe()]}
    assert "error" in agent.submit_artifact(key, "B", {"turn": 1, "plot": ready}, 1)
    for _ in range(2):
        assert agent.submit_artifact(key, "B", {"turn": 2, "plot": ready}, 2)["status"] == "ready"
    detail = drift_plots.detail(store, key)
    html = drift_plots.download(store, key)
    assert detail["artifact_digest"] == hashlib.sha256(html.encode()).hexdigest()
    assert len(detail["history"]) == 2
    assert "/*PLOT_MANIFEST*/null" not in html
    assert answer["answer"] in html


@pytest.mark.parametrize("runs", [
    [recipe(origin_mm=8)], [recipe(context_number=8)], [recipe(ticks_per_mm=4)],
    [recipe(role_column="kind")], [recipe(timestamp_unit="minutes")],
    [recipe(reading_column="time")], [recipe(interval_seconds=0.1)],
    [recipe(filename="a.csv"), recipe(filename="a.csv")], [recipe(), recipe(filename="b.csv")],
])
def test_invalid_recipe_cannot_finish(store, runs):
    key = drift_plots.create(store, "Researcher", request())["id"]
    drift_plots.claim(store, key, "A")
    out = drift_plots.submit(store, key, "A", {"turn": 1, "plot": {"axis": "elapsed", "summary": "Method",
                             "question": "", "runs": runs}})
    assert out["retry"] and not drift_plots.detail(store, key)["history"]


def test_registered_project_is_pinned_and_only_selected_evidence_reaches_author(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    store.put_experiment(experiment_from_dict(b12_experiment_dict))
    doc = b12_experiment_dict["documents"][0]
    key = drift_plots.create(store, "PI", request({"experiment_id": b12_experiment_dict["id"],
                             "experiment_document_ids": [doc["id"]]}))["id"]
    b12_experiment_dict["goal"] = "A subsequent revision"
    store.put_experiment(experiment_from_dict(b12_experiment_dict))
    ctx = AgentTools(store).get_work_order_context(key)["drift_plot"]["contexts"][0]
    assert ctx["lab"]["documents"] == [] and ctx["experiment"]["documents"][0]["id"] == doc["id"]
    assert ctx["experiment"]["revision"] == 1 and "subsequent revision" not in json.dumps(ctx)
