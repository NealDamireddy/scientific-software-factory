import asyncio
from copy import deepcopy
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from labfactory.store import Store
from labfactory.workorders import WorkOrders

from test_claim_recovery_acceptance import (
    FORMER, ORDER, PLAN, REPLACEMENT, REVIEWER, active_claim, claim, cli, db,
    requeue_args, snapshot, submit, successful, worker_call,
)


def response_body(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


@pytest.mark.parametrize(
    "submission",
    ["stale-tagged", "late-untagged", "current-tagged", "first-untagged"],
)
def test_submission_claim_generation(db, submission):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "labfactory", "--db", str(db), "serve"],
            cwd=db.parent,
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "list_work_orders", "get_work_order_context",
                    "claim_work_order", "submit_artifact",
                }
                listed = await session.call_tool("list_work_orders", {"status": "open"})
                assert not listed.isError, listed.content
                context = await session.call_tool("get_work_order_context", {"work_order_id": ORDER})
                assert not context.isError, context.content
                assert response_body(context)["work_order"]["id"] == ORDER

                worker_args = {"work_order_id": ORDER, "worker": FORMER}
                started = await session.call_tool("claim_work_order", worker_args)
                assert not started.isError, started.content
                assert response_body(started)["status"] == "in_progress"
                original_claim = active_claim(db)
                original_payload = {**worker_args, "artifact": PLAN, "claim_id": original_claim}
                untagged_payload = {**worker_args, "artifact": PLAN}

                if submission == "first-untagged":
                    payload = untagged_payload
                else:
                    successful(cli(db, *requeue_args(original_claim)))
                    reclaimed = await session.call_tool("claim_work_order", worker_args)
                    assert not reclaimed.isError, reclaimed.content
                    assert response_body(reclaimed)["status"] == "in_progress"
                    current_claim = active_claim(db)
                    assert current_claim != original_claim
                    payload = {
                        "stale-tagged": original_payload,
                        "late-untagged": untagged_payload,
                        "current-tagged": {**untagged_payload, "claim_id": current_claim},
                    }[submission]

                before = snapshot(db)
                result = await session.call_tool("submit_artifact", payload)
                after = snapshot(db)
                body = {} if result.isError else response_body(result)
                if submission in {"stale-tagged", "late-untagged"}:
                    assert (result.isError or "error" in body, after == before) == (True, True), (
                        f"{submission} must be refused with the order, submissions, and history "
                        f"unchanged, got {body or result.content}"
                    )
                else:
                    assert not result.isError, result.content
                    assert (body.get("passed"), body.get("status"), body.get("submission")) == (
                        True, "in_review", 1,
                    ), body
                    order, submissions, history = after
                    assert order.status == "in_review"
                    booked, = submissions
                    assert booked.artifact_digest == body["artifact_digest"]
                    assert history[:-1] == before[2]
                    assert (history[-1]["event"], history[-1]["actor"]) == ("submitted", FORMER)

    asyncio.run(exercise())


def test_rejected_digests_only_fence_untagged_retries_by_the_same_worker(db, monkeypatch):
    def reject(number):
        with Store(db) as store:
            WorkOrders(store).reject(ORDER, REVIEWER, number, "Revise the plan")

    def unexpected_check(*args):
        pytest.fail("A fenced retry reached artifact checks")

    claim(db)
    assert submit(db)["passed"]
    reject(1)

    before = snapshot(db)
    reordered = dict(reversed(list(PLAN.items())))
    denied_claim = worker_call(db, "claim_work_order", FORMER, reordered)
    assert "previously rejected" in denied_claim["error"]
    assert snapshot(db) == before

    corrected = deepcopy(PLAN)
    corrected["steps"][0]["settings"][0]["value"] += 1
    second_claim = worker_call(db, "claim_work_order", FORMER, corrected)["claim_id"]
    with monkeypatch.context() as patch:
        patch.setattr(WorkOrders, "_check", unexpected_check)
        before = snapshot(db)
        assert "previously rejected" in submit(db, artifact=reordered)["error"]
        assert snapshot(db) == before
    assert submit(db, artifact=corrected)["passed"]
    reject(2)

    current = claim(db)["claim_id"]
    with monkeypatch.context() as patch:
        patch.setattr(WorkOrders, "_check", unexpected_check)
        before = snapshot(db)
        for old_artifact in (PLAN, corrected):
            assert "previously rejected" in submit(db, artifact=old_artifact)["error"]
        stale = worker_call(db, "submit_artifact", FORMER, PLAN, second_claim)
        assert "no longer active" in stale["error"]
        assert snapshot(db) == before
    assert worker_call(db, "submit_artifact", FORMER, PLAN, current)["passed"]
    reject(3)
    claim(db, REPLACEMENT)
    assert submit(db, REPLACEMENT)["passed"]
