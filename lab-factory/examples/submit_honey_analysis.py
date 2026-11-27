"""Submit the source-derived honey analysis to its hosted work order for human review."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from submit_example import ExampleError, call, submit_prebuilt


CANDIDATE = Path(__file__).with_name("honey-analysis.json")
# These are the catalog editions consulted while authoring this submission.
SOURCE_DIGESTS = {
    "hanna-hi96800-manual": "7c1364883c0fe71b94d961332e84607cb5f4df1547b84e05c94605f30a9d52a9",
    "hanna-honey-refractive-index": "2d3d2bc172fdc89492e433270a85a4c9a1988443ee874edf3a3b91748712767d",
    "ihc-2009-honey-moisture": "d78eeb355c7f11a67ae86089e0ae2e882549e6b978e484aed9a9e502e93e0101",
    "barbour-2026-honey-moisture": "0eac7aee4f17fe46b90022d9eabedda977c2206c2a2d6604a2d823d94360438b",
}


async def submit(session, order_id, worker, artifact, claim_id=None):
    context = await call(session, "get_work_order_context", {"work_order_id": order_id})
    order = context["work_order"]
    brief = context.get("reference_brief") or {}
    if (order["kind"] != "analysis_app" or order["experiment_id"] != "honey-moisture-sim-v1"
            or brief.get("instrument", {}).get("id") != "hanna-hi96800"):
        raise ExampleError("Choose a honey analysis order for the Hanna HI96800.")
    pinned = {record["id"]: record["digest"] for record in brief["findings"]}
    if pinned != SOURCE_DIGESTS:
        raise ExampleError("The pinned source editions differ from those used to write this analysis.")
    print(f"{order_id} · {len(pinned)} pinned source editions verified")
    args = {"work_order_id": order_id, "worker": worker}
    submission = await submit_prebuilt(session, order, args, artifact, claim_id)
    print(f"Submission {submission['submission']} · {submission['status']} · SHA-256 {submission['artifact_digest']}")
    for check in submission["results"]:
        outcome = "pass" if check["passed"] else "fail"
        print(f"{outcome}  {check['name']} · {check['detail']}")
    return 0 if submission["passed"] else 1


async def run(url, token, order, worker, artifact, claim_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=45) as client:
        async with streamable_http_client(url, http_client=client) as (receive, send, _):
            async with ClientSession(receive, send) as session:
                await session.initialize()
                try:
                    return await submit(session, order, worker, artifact, claim_id)
                except ExampleError as exc:
                    print(f"error: {exc}", file=sys.stderr)
                    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order", help="Honey analysis work order ID")
    parser.add_argument("--url", required=True, help="Lab Factory HTTPS MCP endpoint")
    parser.add_argument("--worker", required=True, help="Name assigned to your agent token")
    parser.add_argument("--artifact", type=Path, default=CANDIDATE, help="Path to the candidate JSON")
    parser.add_argument("--claim-id", type=int, help="Claim ID saved when starting work on the candidate")
    args = parser.parse_args()
    if urlsplit(args.url).scheme != "https":
        parser.error("The remote MCP URL must use HTTPS")
    token = os.environ.get("LAB_FACTORY_AGENT_TOKEN")
    if not token:
        parser.error("Set LAB_FACTORY_AGENT_TOKEN to the agent's issued credential")
    try:
        candidate = json.loads(args.artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not isinstance(candidate, dict):
        parser.error("The candidate must be a JSON object")
    raise SystemExit(asyncio.run(run(args.url, token, args.order, args.worker, candidate, args.claim_id)))
