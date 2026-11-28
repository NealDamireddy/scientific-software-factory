from copy import deepcopy
from dataclasses import replace

import pytest

from labfactory import procedure_drafts as drafts
from labfactory.agent import AgentTools
from labfactory.context import Document, experiment_from_dict, lab_from_dict
from labfactory.workorders import WorkOrderError, WorkOrders


def test_drafting_from_saved_goal_and_revising_sources(store, uvvis_lab_dict, b12_experiment_dict):
    instrument = uvvis_lab_dict["instruments"][0]
    instrument.update(id="chamber", commands=[{"name": "hold", "required": ["temperature"]}])
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    b12_experiment_dict.update(id="thermal-drift", title="Probe stability", instrument_ids=["chamber"],
                               goal="Record thermal drift of the reference probe.", documents=[])
    exp = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(exp)
    order = drafts.create(store, exp.id, "reviewer")
    assert order.objective == exp.goal
    agent = AgentTools(store)
    agent.claim_work_order(order.id, "worker")
    question = {"needs_input": "Which temperature is specified for the reference probe?"}
    assert not agent.submit_artifact(order.id, "worker", question)["passed"]
    orders = WorkOrders(store)
    with pytest.raises(WorkOrderError):
        orders.approve(order.id, "reviewer", 1)
    text = "\n".join(["Log the chamber ID."] * 21 + ["Hold the reference probe at 20 degC during the drift test."])
    new = drafts.add_source(store, order.id, "reviewer", "Chamber method", text)
    assert orders.get(new).experiment_revision == 2
    assert orders.pinned_context(order.id)[1] == exp
    with pytest.raises(WorkOrderError, match="already exists"):
        drafts.add_source(store, order.id, "reviewer", "Chamber method", text)
    assert "error" in agent.submit_artifact(order.id, "worker", question)
    store.put_experiment(replace(exp, documents=(Document("wrong", "note", "Later", "operator", "Hold at 5 degC."),)))
    context = agent.get_work_order_context(new, "reference probe drift")
    passage = context["passages"][0]
    assert passage["passage"] == 22 and "20 degC" in passage["text"]
    assert "text" not in context["experiment"]["documents"][0]
    assert agent.get_work_order_context(new, "drift", 12)["passages"]
    step = {"text": "Hold the probe at the method temperature.", "citations": [passage["document"]],
            "evidence": [{"document": passage["document"], "quote": passage["text"], "passage": 22}],
            "action": {"command": "hold", "instrument_id": "chamber",
                       "settings": [{"parameter": "temperature", "value": 293.15, "unit": "K"}]}}
    agent.claim_work_order(new, "worker")
    def submit(candidate):
        return agent.submit_artifact(new, "worker", {"steps": [candidate]})
    for key, value in [("quote", "0 degC"), ("quote", "Hold at 21 degC."), ("passage", 1)]:
        bad = deepcopy(step)
        bad["evidence"][0][key] = value
        assert submit(bad)["passed"] is False
    wrong = deepcopy(step)
    wrong["action"]["settings"][0]["value"] = 292.15
    assert not submit(wrong)["passed"]
    assert not submit({k: v for k, v in step.items() if k != "evidence"})["passed"]
    result = submit(step)
    assert result["passed"]
    assert orders.approve(new, "reviewer", result["submission"]).status == "released"
    assert drafts.catalog(store)["experiments"][0]["id"] == exp.id


def test_newer_experiment_preserved(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    exp = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(exp)
    id = drafts.create(store, exp.id, "operator").id
    orders = WorkOrders(store)
    orders.claim(id, "agent")
    orders.submit(id, "agent", {"needs_input": "Which source?"})
    store.put_experiment(replace(exp, goal="A different goal"))
    with pytest.raises(WorkOrderError, match="experiment has changed"):
        drafts.add_source(store, id, "operator", "Source", "Text")
    assert len(orders.list()) == 1
