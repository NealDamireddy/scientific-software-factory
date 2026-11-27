"""Claim a quickstart order and submit its example over MCP stdio."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ExampleError(Exception):
    """A tool or work order reported an expected failure."""


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise ExampleError(f"{name}: {result.content[0].text}")
    # FastMCP sends each list item as its own content block.
    items = [json.loads(block.text) for block in result.content]
    for item in items:
        if "error" in item:
            raise ExampleError(f"{name}: {item['error']}")
    return items if name == "list_work_orders" else items[0]


async def submit_prebuilt(session, order, args, artifact, claim_id):
    order_id = args["work_order_id"]
    if claim_id is not None:
        if claim_id < 1:
            raise ExampleError("Supply a positive --claim-id")
        if order["status"] != "in_progress" or order.get("claim_id") != claim_id:
            raise ExampleError(f"claim {claim_id} is no longer active for {order_id}")
        args = {**args, "claim_id": claim_id}
    if order["status"] == "open":
        await call(session, "claim_work_order", {**args, "untagged_artifact": artifact})
    elif order["status"] != "in_progress" or order["worker"] != args["worker"]:
        raise ExampleError(f"{order_id} is unavailable to this worker")
    # An untagged prebuilt upload must go through the server's ambiguity check.
    return await call(session, "submit_artifact", {**args, "artifact": artifact})


async def submit_order(
    session: ClientSession, order_id: str, worker: str = "example-agent",
    source: str | None = None, claim_id: int | None = None,
) -> int:
    if source is None and claim_id is not None:
        raise ExampleError("--claim-id requires --source")
    await session.initialize()
    tools = await session.list_tools()
    print("MCP tools:", ", ".join(tool.name for tool in tools.tools))
    if source is None:
        orders = await call(session, "list_work_orders", {"status": "open"})
        if not any(order["id"] == order_id for order in orders):
            raise ExampleError(f"{order_id} is not open")
    ids = {"work_order_id": order_id}
    claim = {**ids, "worker": worker}
    context = await call(session, "get_work_order_context", ids)
    order = context["work_order"]
    if order["kind"] == "analysis_app" and source is None:
        raise ExampleError("Supply --source with the Python function to submit")
    if source is not None and order["kind"] != "analysis_app":
        raise ExampleError("--source requires an analysis_app order")
    if source is not None:
        submission = await submit_prebuilt(session, order, claim, {"source": source}, claim_id)
    else:
        order = await call(session, "claim_work_order", claim)
        submission = await call(session, "submit_artifact", {
            **claim, "claim_id": order["claim_id"], "artifact": context["artifact_example"],
        })
    print(f"{order_id} submission {submission['submission']} · {submission['status']}")
    if not submission["passed"]:
        for check in submission["results"]:
            if not check["passed"]:
                print(f"{check['name']}: {check['detail']}", file=sys.stderr)
        return 1
    return 0


async def submit(db: Path, order_id: str, source: str | None = None, claim_id: int | None = None) -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "labfactory", "--db", str(db.resolve()), "serve"],
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            try:
                return await submit_order(session, order_id, source=source, claim_id=claim_id)
            except ExampleError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("order")
    parser.add_argument("--source", type=Path, help="Python source for an analysis_app candidate")
    parser.add_argument("--claim-id", type=int, help="Claim ID saved when starting work on the candidate")
    args = parser.parse_args()
    source = args.source.read_text() if args.source else None
    raise SystemExit(asyncio.run(submit(args.database, args.order, source, args.claim_id)))
