"""Kill and resume a claimed fixed-candidate job against this disposable loopback service."""

import argparse
import asyncio
from contextlib import redirect_stdout
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from time import monotonic
from urllib.parse import urlsplit


HERE = Path(__file__).resolve().parent
WORKER = "trial-resume-probe"


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def worker_process(base, order_id, token, artifact, claimed=None):
    """Run the pinned worker with a fixed test author and an independent MCP connection."""
    import httpx
    from labfactory import tabular_worker
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    def fixed_author(context, feedback):
        if claimed is not None:
            claimed.set()
            threading.Event().wait()
        return artifact

    async def run():
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token}, timeout=20, trust_env=False
        ) as http:
            async with streamable_http_client(base + "/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    processed = await tabular_worker.process(session, order_id, WORKER, author=fixed_author)
                    check(processed, "Pinned worker did not process its assigned order")

    # The pinned worker prints one submission line. Reserve stdout for the JSON report.
    with redirect_stdout(sys.stderr):
        asyncio.run(run())


def run_probe(wire, base, token, manifest, fixture):
    runtime = multiprocessing.get_context("spawn")
    artifact = fixture["artifacts"]["density"]
    order_id = wire.exchange("/api/analysis/orders", fixture["examples"]["density"], 201).json()["id"]
    path = "/api/analysis/orders/" + order_id
    claimed = runtime.Event()
    args = (base, order_id, token, artifact)
    first = runtime.Process(target=worker_process, args=(*args, claimed))
    start = monotonic()
    first.start()
    try:
        check(claimed.wait(30), "First worker did not acknowledge the committed claim")
        before = wire.exchange(path).json()
        check(before["order"]["status"] == "in_progress" and before["order"]["worker"] == WORKER
              and before["submissions"] == [], "Expected a committed claim with zero submissions")
    finally:
        if first.is_alive():
            first.kill()
        first.join(10)
    check(first.exitcode == -signal.SIGKILL, "First worker did not exit by SIGKILL")
    killed_at = monotonic()
    after = wire.exchange(path).json()
    check(after["order"] == before["order"] and after["submissions"] == [], "Claim changed after worker death")
    second = runtime.Process(target=worker_process, args=args)
    second.start()
    try:
        second.join(60)
        check(second.exitcode == 0, "Replacement worker did not finish successfully")
    finally:
        if second.is_alive():
            second.kill()
            second.join(10)
    end = wire.exchange(path).json()
    check(end["order"]["status"] == "in_review" and end["order"]["worker"] == WORKER,
          "Recovered order did not reach human review with its original owner")
    check(len(end["submissions"]) == 1, "Expected exactly one submission on the recovered claim")
    sub = end["submissions"][0]
    expected = manifest["artifact_sha256"]["density"]
    check(sub["number"] == 1 and sub["worker"] == WORKER and sub["artifact"] == artifact
          and sub["artifact_digest"] == expected and sub["control"]["artifact_digest"] == expected,
          "Submission does not match the pinned density artifact")
    check(sub["passed"] is True and sub["control"]["passed"] is True, "Numerical verification failed")
    events = [row["event"] for row in end["history"]]
    check(events.count("claimed") == 1 and events.count("submitted") == 1, "Unexpected claim or submission count")
    return {
        "status": "pass", "order_id": order_id, "worker": WORKER,
        "author": "Injected fixed workload density candidate", "model_generation": False,
        "backend_worker": "labfactory.tabular_worker.process", "transport": "MCP streamable HTTP",
        "original_worker_pid": first.pid, "replacement_worker_pid": second.pid,
        "original_worker_exitcode": first.exitcode, "replacement_worker_exitcode": second.exitcode,
        "status_after_kill": after["order"]["status"], "submissions_after_kill": 0,
        "final_status": end["order"]["status"], "claim_events": events.count("claimed"),
        "submission_count": len(end["submissions"]), "numerical_checks_passed": sub["passed"],
        "blind_control_passed": sub["control"]["passed"], "artifact_sha256": expected,
        "workload_sha256": manifest["workload_sha256"],
        "worker_start_to_kill_seconds": round(killed_at - start, 6),
        "kill_to_verified_submission_seconds": round(monotonic() - killed_at, 6),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--credentials", type=Path, help="Disposable private reviewer credentials from acceptance.py")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urlsplit(base)
    check(url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
          and not any((url.username, url.password, url.path, url.query, url.fragment)),
          "Supply the isolated service's 127.0.0.1 HTTP origin and explicit port")
    run_dir = args.runtime.resolve()
    status = subprocess.run([sys.executable, str(HERE / "service.py"), "status", "--runtime", str(run_dir)],
                            capture_output=True, text=True, check=True)
    service = json.loads(status.stdout)
    check(service["ready"] is True and service["port"] == url.port, "Runtime is not ready on the requested port")
    token = os.environ.pop("TRIAL_PROBE_WORKER_TOKEN", "")
    check(token, "The trial driver must supply TRIAL_PROBE_WORKER_TOKEN")
    src = run_dir / "package" / "lab-factory" / "src"
    check((src / "labfactory" / "tabular_worker.py").is_file(), "Pinned worker package is missing")
    sys.path.insert(0, str(src))
    sys.path.insert(0, str(HERE.parents[1]))
    import acceptance

    manifest, fixture = acceptance.workload()
    creds = acceptance.load_credentials(args.credentials, loopback=True)
    wire = acceptance.Wire(base, creds, loopback=True)
    try:
        print(json.dumps(run_probe(wire, base, token, manifest, fixture), indent=2))
    finally:
        wire.client.close()


if __name__ == "__main__":
    main()
