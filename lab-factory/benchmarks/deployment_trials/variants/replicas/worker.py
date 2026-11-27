"""One-job deterministic MCP worker for the local replicated deployment trial."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CASES = ("caffeine", "density", "wrong")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(artifact):
    return json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checked(artifact, case, manifest):
    if digest(canonical(artifact)) != manifest["artifact_sha256"][case]:
        raise ValueError(f"Shared artifact digest mismatch for {case}.")
    return artifact


def prepare(directory, manifest):
    # The operator extracts only the fixed author-side payloads before launching the client.
    raw = (FIXTURES / "workload.json").read_bytes()
    if digest(raw) != manifest["workload_sha256"]:
        raise ValueError("Shared workload digest mismatch.")
    artifacts = json.loads(raw)["artifacts"]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for case in CASES:
        content = canonical(checked(artifacts[case], case, manifest))
        (directory / f"{case}.json").write_bytes(content)


async def call(session, method, arguments):
    reply = await session.call_tool(method, arguments)
    if reply.isError or len(reply.content) != 1:
        raise RuntimeError(f"MCP {method} failed.")
    result = json.loads(reply.content[0].text)
    if not isinstance(result, dict) or "error" in result:
        raise RuntimeError(f"Backend rejected {method}.")
    return result


async def process(args, manifest):
    origin = urlsplit(args.base_url)
    if (origin.scheme != "http" or origin.hostname != "127.0.0.1" or origin.username is not None
            or origin.password is not None or origin.path not in ("", "/") or origin.query or origin.fragment):
        raise ValueError("Supply the trial's loopback HTTP origin on 127.0.0.1.")
    token = args.token_file.read_text().strip()
    if not token:
        raise ValueError("Worker token file is empty.")
    artifact = checked(json.loads((args.artifact_dir / f"{args.case}.json").read_bytes()), args.case, manifest)
    key = {"work_order_id": args.order}
    identity = {**key, "worker": args.worker}
    start = time.monotonic()

    def emit(event, **fields):
        print(json.dumps({"event": event, "worker_pid": os.getpid(), **key,
                          "elapsed_ms": round((time.monotonic() - start) * 1000, 2), **fields}), flush=True)

    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=30) as http:
        async with streamable_http_client(args.base_url.rstrip("/") + "/mcp", http_client=http) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                context = await call(session, "get_work_order_context", key)
                order = context["work_order"]
                analysis = context["analysis"]
                if order["status"] in ("in_review", "released"):
                    emit("already_submitted", status=order["status"])
                    return
                if analysis["awaiting_fresh_control"] or analysis["needs_input"]:
                    raise RuntimeError("Reviewer input is required before submission.")
                if order["status"] == "open":
                    claim = await call(session, "claim_work_order", identity)
                    if claim["status"] != "in_progress" or claim["worker"] != args.worker:
                        raise RuntimeError("Claim did not bind this worker identity.")
                    action = "claimed"
                elif order["status"] == "in_progress" and order["worker"] == args.worker:
                    action = "resumed"
                else:
                    raise RuntimeError("Order unavailable to this worker identity.")
                emit("ready_after_claim", action=action, status="in_progress")
                if args.hold_after_claim:
                    # The test controller kills this process at a confirmed durable boundary.
                    await asyncio.Event().wait()
                result = await call(session, "submit_artifact", {**identity, "artifact": artifact})
                if result["artifact_digest"] != manifest["artifact_sha256"][args.case]:
                    raise RuntimeError("Submitted artifact digest mismatch.")
                emit("submitted", **{k: result[k] for k in ("submission", "artifact_digest", "status", "passed")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", help="Project fixed candidates into a worker fixture directory")
    submit = commands.add_parser("process", help="Claim or resume one specific order through the proxy")
    for sub in (prepare_cmd, submit):
        sub.add_argument("--artifact-dir", type=Path, required=True)
    submit.add_argument("--base-url", required=True)
    submit.add_argument("--order", required=True)
    submit.add_argument("--worker", required=True)
    submit.add_argument("--token-file", type=Path, required=True)
    submit.add_argument("--case", required=True, choices=CASES)
    submit.add_argument("--hold-after-claim", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
    if args.command == "prepare":
        prepare(args.artifact_dir, manifest)
    else:
        asyncio.run(process(args, manifest))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, ExceptionGroup) as exc:
        # Transport bodies, HTTP headers and reviewer data have no place in trial evidence.
        print(json.dumps({"event": "failed", "error_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
