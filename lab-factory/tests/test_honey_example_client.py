import asyncio
import json
from pathlib import Path

import pytest

from labfactory.references import search


@pytest.fixture
def sender(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "examples"))
    import submit_honey_analysis

    return submit_honey_analysis


@pytest.fixture
def order_context():
    return {
        "work_order": {"kind": "analysis_app", "experiment_id": "honey-moisture-sim-v1",
                       "status": "open", "worker": None},
        "reference_brief": search("hanna-hi96800", "Measure honey moisture"),
    }


def tool_stub(sender, monkeypatch, context):
    import submit_example

    calls = []

    async def call(session, name, arguments):
        calls.append((name, arguments))
        if name == "get_work_order_context":
            return context
        if name == "claim_work_order":
            return {"claim_id": 2}
        assert name == "submit_artifact"
        return {"submission": 1, "status": "in_review", "artifact_digest": "abc",
                "results": [], "passed": True}

    monkeypatch.setattr(sender, "call", call)
    monkeypatch.setattr(submit_example, "call", call)
    return calls


@pytest.mark.parametrize(("status", "claim_id"), [
    ("open", None), ("in_progress", None), ("in_progress", 2),
])
def test_sender_preserves_caller_binding(sender, monkeypatch, order_context, status, claim_id):
    order_context["work_order"].update(
        status=status, worker="agent" if status == "in_progress" else None,
        claim_id=2 if status == "in_progress" else None,
    )
    calls = tool_stub(sender, monkeypatch, order_context)
    artifact = json.loads(sender.CANDIDATE.read_text())
    assert asyncio.run(sender.submit(None, "WO-1", "agent", artifact, claim_id)) == 0
    expected = ["get_work_order_context", "submit_artifact"]
    if status == "open":
        expected.insert(1, "claim_work_order")
    assert [name for name, args in calls] == expected
    submitted = {"work_order_id": "WO-1", "worker": "agent", "artifact": artifact}
    if claim_id is not None:
        submitted["claim_id"] = claim_id
    assert calls[-1][1] == submitted


@pytest.mark.parametrize("status", ["open", "in_progress"])
def test_sender_rejects_stale_binding_before_claim_or_submit(sender, monkeypatch, order_context, status):
    order_context["work_order"].update(
        status=status, worker="agent" if status == "in_progress" else None,
        claim_id=2 if status == "in_progress" else None,
    )
    calls = tool_stub(sender, monkeypatch, order_context)
    with pytest.raises(sender.ExampleError, match="claim 1 is no longer active"):
        asyncio.run(sender.submit(None, "WO-1", "agent", {}, claim_id=1))
    assert [name for name, args in calls] == ["get_work_order_context"]


@pytest.mark.parametrize("problem", ["edition", "experiment", "instrument", "owner"])
def test_sender_checks_target_before_changing_state(sender, monkeypatch, order_context, problem):
    if problem == "edition":
        order_context["reference_brief"]["findings"][0]["digest"] = "0" * 64
    elif problem == "experiment":
        order_context["work_order"]["experiment_id"] = "b12-sim"
    elif problem == "instrument":
        order_context["reference_brief"]["instrument"] = {"id": "another-model"}
    else:
        order_context["work_order"].update(status="in_progress", worker="different-agent")
    calls = tool_stub(sender, monkeypatch, order_context)
    with pytest.raises(sender.ExampleError):
        asyncio.run(sender.submit(None, "WO-1", "agent", {}))
    assert [name for name, args in calls] == ["get_work_order_context"]
