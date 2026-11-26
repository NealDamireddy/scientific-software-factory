import asyncio
import json
from copy import deepcopy

import pytest

from labfactory.agent import AgentTools
from labfactory.artifacts import ARTIFACT_EXAMPLES
from labfactory.context import canonical_digest, experiment_from_dict, lab_from_dict
from labfactory.mcp_server import build_server
from labfactory.workorders import WorkOrders


@pytest.fixture
def order_id(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    experiment = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(experiment)
    return WorkOrders(store).create(experiment.id, "run_plan", "Read absorbance.").id


def test_agent_flow_returns_plain_dicts(store, order_id, uvvis_lab_dict, b12_experiment_dict):
    agent = AgentTools(store)
    orders = agent.list_work_orders()
    assert [order["id"] for order in orders] == [order_id]
    uvvis_lab_dict["instruments"][0]["firmware"] = "newer"
    b12_experiment_dict["goal"] = "Revised goal"
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    store.put_experiment(experiment_from_dict(b12_experiment_dict))
    context = agent.get_work_order_context(order_id)
    assert set(context) == {"work_order", "lab", "experiment", "artifact_example", "instructions", "previous_rejection"}
    assert context["previous_rejection"] is None
    assert context["lab"]["instruments"][0]["firmware"] == "2.3.1"
    assert context["lab"]["instruments"][0]["commands"][0]["name"] == "read_absorbance"
    assert context["experiment"]["goal"] != "Revised goal"
    claim = agent.claim_work_order(order_id, "codex")
    assert claim["status"] == "in_progress"
    assert agent.list_work_orders() == []
    payload = context["artifact_example"]
    payload["steps"][0]["settings"][0]["value"] = 800
    failure = agent.submit_artifact(order_id, "codex", payload)
    assert failure["status"] == "in_progress" and failure["passed"] is False
    assert any("outside" in result["detail"] for result in failure["results"] if not result["passed"])
    valid = agent.get_work_order_context(order_id)["artifact_example"]
    assert valid["steps"][0]["settings"][0]["value"] == 550
    result = agent.submit_artifact(order_id, "codex", valid)
    assert result["status"] == "in_review" and result["passed"] is True
    assert result["submission"] == 2 and result["artifact_digest"] == canonical_digest(valid)
    assert all(set(check) == {"name", "passed", "detail"} for check in result["results"])
    assert json.loads(json.dumps([orders, context, claim, failure, result])) == [orders, context, claim, failure, result]


def test_errors_are_returned_not_raised(store, order_id):
    agent = AgentTools(store)
    payload = ARTIFACT_EXAMPLES["run_plan"]
    assert "error" in agent.get_work_order_context("unknown")
    assert "error" in agent.submit_artifact(order_id, "codex", payload)
    agent.claim_work_order(order_id, "codex")
    assert "error" in agent.claim_work_order(order_id, "claude")
    assert "error" in agent.submit_artifact(order_id, "codex", {})
    assert WorkOrders(store).submissions(order_id) == []


def test_rejected_work_reaches_next_agent(store, order_id):
    agent = AgentTools(store)
    agent.claim_work_order(order_id, "codex")
    payload = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    payload["steps"][0]["settings"][0]["value"] = 550.0004
    assert agent.submit_artifact(order_id, "codex", payload)["passed"]
    WorkOrders(store).reject(order_id, "Neal", 1, "use 2x dilution")
    assert agent.claim_work_order(order_id, "claude")["worker"] == "claude"
    assert agent.get_work_order_context(order_id)["previous_rejection"] == {
        "by": "Neal", "submission": 1, "reason": "use 2x dilution", "artifact": payload,
    }


def test_server_exposes_no_approval(tmp_path):
    tools = asyncio.run(build_server(str(tmp_path / "stdio.db")).list_tools())
    assert {tool.name for tool in tools} == {
        "list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact",
    }
