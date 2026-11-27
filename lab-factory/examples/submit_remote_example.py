"""Claim an open hosted example order and submit it for human review."""

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from submit_example import ExampleError, submit_order


async def run(url, token, order, worker, source=None, claim_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        async with streamable_http_client(url, http_client=client) as (receive, send, _):
            async with ClientSession(receive, send) as session:
                try:
                    return await submit_order(session, order, worker, source, claim_id)
                except ExampleError as exc:
                    raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order", help="Open example work order ID, such as WO-3")
    parser.add_argument("--url", required=True, help="Lab Factory HTTPS MCP endpoint")
    parser.add_argument("--worker", required=True, help="Name assigned to your agent token")
    parser.add_argument("--source", type=Path, help="Python source for an analysis_app candidate")
    parser.add_argument("--claim-id", type=int, help="Claim ID saved when starting work on the candidate")
    args = parser.parse_args()
    if urlsplit(args.url).scheme != "https":
        parser.error("The remote MCP URL must use HTTPS")
    token = os.environ.get("LAB_FACTORY_AGENT_TOKEN")
    if not token:
        parser.error("Set LAB_FACTORY_AGENT_TOKEN to the agent's issued credential")
    source = args.source.read_text(encoding="utf-8") if args.source else None
    raise SystemExit(asyncio.run(run(args.url, token, args.order, args.worker, source, args.claim_id)))
