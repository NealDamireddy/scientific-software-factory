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


async def submit_order(session: ClientSession, order_id: str) -> int:
    await session.initialize()
    tools = await session.list_tools()
    print("MCP tools:", ", ".join(tool.name for tool in tools.tools))
    orders = await call(session, "list_work_orders", {"status": "open"})
    if not any(order["id"] == order_id for order in orders):
        raise ExampleError(f"{order_id} is not open")
    ids = {"work_order_id": order_id}
    claim = {**ids, "worker": "example-agent"}
    await call(session, "claim_work_order", claim)
    context = await call(session, "get_work_order_context", ids)
    submission = await call(session, "submit_artifact", {
        **claim, "artifact": context["artifact_example"],
    })
    print(f"{order_id} submission {submission['submission']} · {submission['status']}")
    if not submission["passed"]:
        for check in submission["results"]:
            if not check["passed"]:
                print(f"{check['name']}: {check['detail']}", file=sys.stderr)
        return 1
    return 0


async def submit(db: Path, order_id: str) -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "labfactory", "--db", str(db.resolve()), "serve"],
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            try:
                return await submit_order(session, order_id)
            except ExampleError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("order")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(submit(args.database, args.order)))
