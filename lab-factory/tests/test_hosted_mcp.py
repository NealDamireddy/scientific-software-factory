import asyncio
from contextlib import asynccontextmanager
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.hosted_mcp import make_mcp_app
from labfactory.store import Store
from labfactory.workorders import WorkOrders


ORIGIN = "https://lab.example.test"
TOOL_NAMES = {"list_work_orders", "claim_work_order", "get_work_order_context", "submit_artifact"}


@pytest.fixture
def hosted(tmp_path, uvvis_lab_dict, b12_experiment_dict, monkeypatch):
    path = tmp_path / "lab.db"
    with Store(path) as store:
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        exp = experiment_from_dict(b12_experiment_dict)
        store.put_experiment(exp)
        WorkOrders(store).create(exp.id, "run_plan", "Read absorbance")

    def run_store(operation, *, write=False):
        with Store(path) as store:
            return operation(store)

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "lab.example.test")
    monkeypatch.delenv("VERCEL_URL", raising=False)
    monkeypatch.delenv("LABFACTORY_PUBLIC_ORIGIN", raising=False)
    tokens = {"Bearer example-token-A": "agent-a", "Bearer example-token-B": "agent-b"}
    return make_mcp_app(run_store, lambda headers: tokens.get(headers.get("authorization")))


@asynccontextmanager
async def agent(app, token):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, headers={"Authorization": "Bearer " + token}) as client:
        async with streamable_http_client(ORIGIN + "/mcp", http_client=client) as (receive, send, session_id):
            async with ClientSession(receive, send) as session:
                await session.initialize()
                assert session_id() is None
                yield session


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


def test_streamable_http_bound_worker_and_persistent_submission(hosted):
    async def run():
        async with agent(hosted, "example-token-A") as first, agent(hosted, "example-token-B") as second:
            tools = await first.list_tools()
            assert {tool.name for tool in tools.tools} == TOOL_NAMES
            pending = await call(first, "list_work_orders", {})
            work_id = {"work_order_id": pending["id"]}
            ctx = await call(first, "get_work_order_context", work_id)
            artifact = ctx["artifact_example"]
            claim_a = {**work_id, "worker": "agent-a"}
            assert "error" in await call(second, "claim_work_order", claim_a)
            assert (await call(first, "claim_work_order", claim_a))["status"] == "in_progress"
            payload = {**claim_a, "artifact": artifact}
            assert "error" in await call(second, "submit_artifact", payload)
            passed = await call(first, "submit_artifact", payload)
            assert passed["status"] == "in_review" and passed["passed"]
        async with agent(hosted, "example-token-B") as new_session:
            assert (await call(new_session, "get_work_order_context", work_id))["work_order"]["status"] == "in_review"

    asyncio.run(run())


def test_http_transport_rejects_invalid_auth_host_and_origin(hosted):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=hosted)) as client:
            url = ORIGIN + "/mcp/"
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            good = {"Authorization": "Bearer example-token-A", "Accept": "application/json, text/event-stream"}
            for headers in [{}, {"Authorization": "Bearer unknown"}, {"Cookie": "reviewer_session=some-value"}]:
                denied = await client.post(url, json=body, headers=headers)
                assert denied.status_code == 401 and "Bearer" in denied.headers["www-authenticate"]
            wrong_origin = await client.post(url, json=body, headers={**good, "Origin": "https://external.test"})
            assert wrong_origin.status_code == 403
            wrong_host = await client.post("https://external.test/mcp", json=body, headers=good)
            assert wrong_host.status_code == 421
            accepted = await client.post(url, json=body, headers={**good, "Origin": ORIGIN})
            assert accepted.status_code == 200

    asyncio.run(run())


def test_concurrent_remote_claims_keep_agent_identities_separate(hosted):
    async def run():
        async with agent(hosted, "example-token-A") as first, agent(hosted, "example-token-B") as second:
            work_id = {"work_order_id": "WO-1"}
            results = await asyncio.gather(
                call(first, "claim_work_order", {**work_id, "worker": "agent-a"}),
                call(second, "claim_work_order", {**work_id, "worker": "agent-b"}),
            )
            assert sum("error" in result for result in results) == 1
            winner = next(result["worker"] for result in results if "error" not in result)
            context = await call(first, "get_work_order_context", work_id)
            assert context["work_order"]["worker"] == winner

    asyncio.run(run())


def test_mcp_uncertain_write_requires_context_check(monkeypatch):
    monkeypatch.setenv("LABFACTORY_PUBLIC_ORIGIN", ORIGIN)
    def unavailable(operation, *, write=False):
        raise RuntimeError("private provider connection details")
    app = make_mcp_app(unavailable, lambda headers: "agent-a")

    async def run():
        async with agent(app, "temporary") as session:
            result = await session.call_tool("claim_work_order", {"work_order_id": "WO-1", "worker": "agent-a"})
            assert result.isError
            message = result.content[0].text
            assert "could not be confirmed" in message and "get_work_order_context" in message
            assert "private provider" not in message

    asyncio.run(run())


def test_hosted_submission_size_limits_before_core(hosted):
    async def run():
        args = {"work_order_id": "WO-1", "worker": "agent-a"}
        async with agent(hosted, "example-token-A") as session:
            await call(session, "claim_work_order", args)
            for artifact, expected in [
                ({"steps": [{"text": "Ω" * 65536}]}, "128 KiB"),
                ({"steps": [{}] * 257}, "256 steps"),
                ({"instrument_id": "x" * 257}, "instrument_id"),
                ({"steps": [{"action": {"instrument_id": "x" * 257}}]}, "instrument_id"),
                ({"steps": [{"command": "x" * 257}]}, "command"),
                ({"steps": [{"settings": [{}] * 257}]}, "256 settings"),
            ]:
                result = await call(session, "submit_artifact", {**args, "artifact": artifact})
                assert expected in result["error"]
            context = await call(session, "get_work_order_context", {"work_order_id": "WO-1"})
            assert context["work_order"]["status"] == "in_progress"
            result = await call(session, "submit_artifact", {**args, "artifact": context["artifact_example"]})
            assert result["passed"] and result["submission"] == 1

    asyncio.run(run())
