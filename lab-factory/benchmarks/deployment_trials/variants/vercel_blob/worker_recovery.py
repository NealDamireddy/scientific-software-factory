"""Supplemental crash drill for the pinned tabular worker over its real MCP connection."""

import asyncio
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import threading
from time import monotonic
from urllib.parse import urlsplit


HERE = Path(__file__).resolve()


async def child(job):
    import httpx
    from labfactory import tabular_worker
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    if Path(tabular_worker.__file__).resolve() != Path(job["source"]) / "src/labfactory/tabular_worker.py":
        raise ValueError("Analysis worker was not loaded from the pinned source")

    def author(context, feedback):
        if job["phase"] == "hold":
            print("author entered", flush=True)
            threading.Event().wait()
        if job["phase"] == "replay":
            raise ValueError("Completed work unexpectedly reached the author again")
        return job["artifact"]

    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + job["token"]},
                                 timeout=30, trust_env=False) as http:
        async with streamable_http_client(job["base"] + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                processed = await tabular_worker.process(session, job["order"], job["worker"], author)
                if processed != (job["phase"] == "resume"):
                    raise ValueError("Unexpected result from pinned analysis worker")


def probe(source: Path, base: str, credentials: dict, fixture: dict) -> dict:
    """Create a supplemental density order on the running, disposable local trial."""
    origin = urlsplit(base)
    if (origin.scheme != "http" or origin.hostname != "127.0.0.1" or not origin.port
            or any((origin.username, origin.password, origin.path, origin.query, origin.fragment))):
        raise ValueError("Supply the isolated trial's loopback HTTP origin")
    source = source.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("comparison_acceptance", HERE.parents[2] / "acceptance.py")
    runner = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(source / "src"))
    try:
        spec.loader.exec_module(runner)
    finally:
        sys.path.pop(0)
    worker, other = runner.WORKERS
    artifact = fixture["artifacts"]["density"]
    digest = runner.sha(runner.canonical(artifact))
    env = {"PATH": os.defpath, "PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    wire = runner.Wire(base, credentials, True)
    with closing(wire.client):
        order = wire.exchange("/api/analysis/orders", fixture["examples"]["density"], 201).json()["id"]
        path = "/api/analysis/orders/" + order
        args = [sys.executable, "-B", str(HERE)]
        job = {"source": str(source), "order": order, "base": base, "worker": worker,
               "token": credentials["tokens"][worker], "artifact": artifact}
        def payload(phase):
            return json.dumps(job | {"phase": phase}).encode()

        started = monotonic()
        # The HTTP client and the MCP session are fresh in each child. The sole
        # credential it receives is its own bearer token, passed over private stdin.
        with subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as first:
            try:
                first.stdin.write(payload("hold"))
                first.stdin.close()
                runner.require(select.select([first.stdout], [], [], 35)[0] and
                               first.stdout.readline() == b"author entered\n", "First worker never reached its author")
                before = wire.exchange(path).json()
                runner.require(before["order"]["status"] == "in_progress" and before["order"]["worker"] == worker
                               and before["submissions"] == [], "Claim was not committed before the interruption")
            finally:
                if first.poll() is None:
                    first.kill()
                first.wait(timeout=10)
        killed = monotonic()
        runner.require(first.returncode == -signal.SIGKILL, "First worker did not exit by SIGKILL")
        rejection = runner.claim(wire, other, order)
        runner.require("error" in rejection, "Second identity claimed another worker's order")
        after = wire.exchange(path).json()
        for field in ("order", "history", "submissions"):
            runner.require(after[field] == before[field], "Persisted work changed after worker death or competing claim")

        def run_child(phase):
            with subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
                try:
                    process.communicate(input=payload(phase), timeout=45)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                runner.require(process.returncode == 0, f"{phase} worker exited before verification")
                return process.pid

        resume_pid = run_child("resume")
        end = wire.exchange(path).json()
        verified = monotonic()
        runner.require(end["order"]["status"] == "in_review" and end["order"]["worker"] == worker,
                       "Replacement worker did not submit the original claim for review")
        sub, = end["submissions"]
        runner.require(sub["worker"] == worker and sub["number"] == 1 and sub["artifact"] == artifact
                       and sub["artifact_digest"] == digest and sub["control"]["artifact_digest"] == digest
                       and sub["passed"] is True and sub["control"]["passed"] is True,
                       "Replacement submission did not pass with the identical pinned candidate")
        events = [r["event"] for r in end["history"]]
        runner.require(events.count("claimed") == events.count("submitted") == 1, "Duplicated worker event")
        replay_pid = run_child("replay")
        replayed = wire.exchange(path).json()
        for field in ("order", "history", "submissions"):
            runner.require(replayed[field] == end[field], "A repeat worker invocation changed the completed submission")
        runner.require(len({first.pid, resume_pid, replay_pid}) == 3, "Expected distinct worker processes")
    return {
        "status": "pass", "backend_worker": "labfactory.tabular_worker.process", "transport": "MCP streamable HTTP",
        "author": "Injected fixed density candidate", "model_generation": False, "worker_identity": worker,
        "interrupted_exitcode": first.returncode, "distinct_worker_processes": 3,
        "status_after_kill": after["order"]["status"], "submissions_after_kill": len(after["submissions"]),
        "competing_identity_claim_denied": True, "final_status": end["order"]["status"],
        "claim_events": events.count("claimed"), "submitted_events": events.count("submitted"),
        "submission_count": len(end["submissions"]), "submission_number": sub["number"],
        "artifact_sha256": digest, "verification_passed": sub["passed"], "blind_control_passed": sub["control"]["passed"],
        "replay_history_and_submissions_unchanged": True, "elapsed_seconds": {
            "first_start_to_kill": round(killed-started, 4), "kill_to_verified_submission": round(verified-killed, 4),
            "additional_replay": round(monotonic()-verified, 4)},
    }


if __name__ == "__main__":
    asyncio.run(child(json.load(sys.stdin)))
