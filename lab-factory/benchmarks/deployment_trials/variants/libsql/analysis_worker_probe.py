"""Interrupt and resume a supplemental density order after common acceptance verification."""

import asyncio
import json
from pathlib import Path
import runpy
import selectors
import signal
import subprocess
import sys
import tempfile
import time


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


async def worker(mode, origin, order_id, name):
    import httpx
    from labfactory import tabular_worker
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    task = json.load(sys.stdin)
    pinned = Path(task["src"]) / "labfactory" / "tabular_worker.py"
    require(Path(tabular_worker.__file__).resolve() == pinned.resolve(), "Worker import escaped pinned source")

    def author(context, feedback):
        require(context.get("analysis") and "control_expected" not in json.dumps(context),
                "Worker author context must omit the held-back expected value")
        if mode == "claim":
            # process() reaches the author only after the MCP claim returned.
            print("claimed", flush=True)
            time.sleep(45)
            raise TimeoutError("The parent did not interrupt the paused worker")
        return task["candidate"]

    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + task["token"]},
                                 timeout=15, trust_env=False) as client:
        async with streamable_http_client(origin + "/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if mode == "resume":
                    rows = await tabular_worker._call(session, "list_work_orders", {"status": "in_progress"})
                    found = [r for r in rows if r["id"] == order_id and r["worker"] == name
                             and r["kind"] == "analysis_app" and r["experiment_id"].startswith("tabular-")]
                    require(len(found) == 1, "Replacement failed to rediscover the interrupted analysis")
                    order_id = found[0]["id"]
                require(await tabular_worker.process(session, order_id, name, author=author),
                        "Pinned worker declined analysis")


def run_probe(origin, credentials_path, scratch_root, child_env):
    shared = runpy.run_path(str(Path(__file__).resolve().parents[2] / "acceptance.py"))
    base, loopback = shared["read_origin"](origin, False)
    creds = shared["load_credentials"](Path(credentials_path), loopback)
    manifest, fixtures = shared["workload"]()
    name = shared["WORKERS"][0]
    env = {k: child_env[k] for k in ("PATH", "TMPDIR", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE") if k in child_env}
    require("PYTHONPATH" in env, "Pinned worker source directory must be supplied")
    wire = shared["Wire"](base, creds, loopback)
    try:
        order = wire.exchange("/api/analysis/orders", fixtures["examples"]["density"], 201).json()["id"]
        path = "/api/analysis/orders/" + order
        command = [sys.executable, str(Path(__file__).resolve())]
        suffix = [base, order, name]
        payload = {"token": creds["tokens"][name], "src": env["PYTHONPATH"]}
        with tempfile.TemporaryDirectory(dir=scratch_root, prefix="analysis-workers-") as cwd:
            start = time.perf_counter()
            first = subprocess.Popen([*command, "claim", *suffix], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=cwd, env=env, text=True)
            try:
                first.stdin.write(json.dumps(payload))
                first.stdin.close()
                with selectors.DefaultSelector() as selector:
                    selector.register(first.stdout, selectors.EVENT_READ)
                    require(selector.select(25) and first.stdout.readline().strip() == "claimed",
                            "First analysis worker failed to acknowledge its claim")
                before = wire.exchange(path).json()
                require(before["order"]["status"] == "in_progress" and before["order"]["worker"] == name
                        and before["submissions"] == [] and first.poll() is None,
                        "Reviewer could not confirm the live worker's unsubmitted claim")
                kill_time = time.perf_counter()
            finally:
                if first.poll() is None:
                    first.kill()
                first.wait(timeout=8)
                first.stdout.close()
                first.stdin.close()
            require(first.returncode == -signal.SIGKILL, "First worker did not die by SIGKILL")
            after = wire.exchange(path).json()
            require(after == before, "Author death changed the saved order or its submissions")
            payload["candidate"] = fixtures["artifacts"]["density"]
            replacement_start = time.perf_counter()
            with subprocess.Popen([*command, "resume", *suffix], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, env=env, cwd=cwd, text=True) as second:
                try:
                    second.communicate(input=json.dumps(payload), timeout=45)
                finally:
                    if second.poll() is None:
                        second.kill()
                    second.wait(timeout=8)
            require(second.returncode == 0 and second.pid != first.pid, "Replacement analysis worker failed")
        final = wire.exchange(path).json()
        verified = time.perf_counter()
        events = final["history"]
        claims = [e for e in events if e["event"] == "claimed"]
        submits = [e for e in events if e["event"] == "submitted"]
        require(len(claims) == len(submits) == len(final["submissions"]) == 1
                and claims[0]["actor"] == submits[0]["actor"] == name and submits[0]["submission"] == 1,
                "Unexpected worker, claim, or submission history")
        artifact = final["submissions"][0]
        digest = manifest["artifact_sha256"]["density"]
        require(final["order"]["status"] == "in_review" and final["order"]["worker"] == name
                and artifact["number"] == 1 and artifact["worker"] == name
                and artifact["artifact"] == payload["candidate"]
                and artifact["artifact_digest"] == artifact["control"]["artifact_digest"] == digest
                and artifact["passed"] is True and artifact["control"]["passed"] is True,
                "Recovered submission did not pass the independent control with the pinned candidate")
        return {
            "status": "pass", "order_id": order, "worker_identity": name,
            "worker_function": "labfactory.tabular_worker.process",
            "author": "fixed shared density candidate", "model_generation": False,
            "transport": "authenticated streamable HTTP MCP", "reviewer_mode": "public" if wire.public else "named",
            "original_pid": first.pid, "replacement_pid": second.pid,
            "original_exit_code": first.returncode, "replacement_exit_code": second.returncode,
            "replacement_found_via_in_progress_list": True, "status_after_sigkill": after["order"]["status"],
            "submissions_after_sigkill": len(after["submissions"]), "final_status": final["order"]["status"],
            "claim_events": len(claims), "submission_events": len(submits), "submission_count": len(final["submissions"]),
            "artifact_sha256": digest, "passed": artifact["passed"], "blind_control_passed": artifact["control"]["passed"],
            "workload_sha256": manifest["workload_sha256"],
            "worker_spawn_to_confirmed_claim_ms": round((kill_time - start) * 1000, 2),
            "kill_to_verified_submission_ms": round((verified - kill_time) * 1000, 2),
            "replacement_spawn_to_verified_submission_ms": round((verified - replacement_start) * 1000, 2),
        }
    finally:
        wire.client.close()


if __name__ == "__main__":
    mode, origin, order_id, identity = sys.argv[1:]
    require(mode in ("claim", "resume"), "Unknown worker mode")
    asyncio.run(worker(mode, origin, order_id, identity))
