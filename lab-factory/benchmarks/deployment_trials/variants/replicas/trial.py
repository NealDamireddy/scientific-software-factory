"""Exercise the common workload, replica loss and deterministic worker recovery over loopback."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time

import httpx


HERE = Path(__file__).resolve().parent
TRIALS = HERE.parents[1]
PYTHON = TRIALS.parents[1] / ".venv/bin/python"
ACCEPTANCE = TRIALS / "acceptance.py"
COMMIT = "62badef1d608d94903da475bfd2b689cb80f9c49"
AGENT = "agent-a"


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_bytes())


def digest(data):
    return sha256(data).hexdigest()


def child_env():
    return {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ} | {
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
    }


def command(script, *args, env=None):
    result = subprocess.run([PYTHON, "-B", script, *args], env=env or child_env(),
                            stdout=subprocess.PIPE, text=True, check=True, timeout=150)
    return result.stdout


def milliseconds(start):
    return round((time.perf_counter() - start) * 1000, 2)


def listener_down(port):
    # A different listener on the expected port is also a failed offline assertion.
    try:
        httpx.get(f"http://127.0.0.1:{port}/api/session", trust_env=False, timeout=1)
    except httpx.ConnectError:
        return True
    return False


def database_info(path):
    stat = path.stat()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
    check((mode, integrity) == ("wal", "ok"), "SQLite WAL/integrity check failed")
    return {"device": stat.st_dev, "inode": stat.st_ino, "journal_mode": mode, "quick_check": integrity}


def pids(status):
    return {name: data["pid"] for name, data in status["processes"].items()}


def read_order(client, path):
    start = time.perf_counter()
    response = client.get(path)
    response.raise_for_status()
    detail = response.json()
    sample = {"replica": response.headers["x-lab-replica"], "http_status": response.status_code,
              "elapsed_ms": milliseconds(start), "body_sha256": digest(response.content),
              "order_id": detail["order"]["id"], "status": detail["order"]["status"],
              "submissions": len(detail["submissions"])}
    return detail, sample


def alternate(samples):
    observed = [sample["replica"] for sample in samples]
    check(observed in (["a", "b", "a", "b"], ["b", "a", "b", "a"]), "Round robin did not alternate")


def claim_and_interrupt(args, other_pids):
    start = time.perf_counter()
    with subprocess.Popen([PYTHON, "-B", HERE / "worker.py", *args, "--hold-after-claim"], env=child_env(),
                          stdout=subprocess.PIPE, text=True) as worker:
        try:
            ready, _, _ = select.select([worker.stdout], [], [], 30)
            check(ready, "Worker timed out before its durable claim")
            event = json.loads(worker.stdout.readline())
            check(event["event"] == "ready_after_claim" and event["action"] == "claimed"
                  and event["worker_pid"] == worker.pid and worker.pid not in other_pids,
                  "Expected an independent worker process to claim the supplemental job")
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=10)
    check(worker.returncode == -signal.SIGKILL, "Worker interruption was not confirmed")
    return {"marker": event, "exit_code": worker.returncode, "start_to_kill_ms": milliseconds(start)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18460, help="Proxy port. API replicas use the next two ports.")
    parser.add_argument("--output", required=True, type=Path, help="Directory for acceptance.json and evidence.json")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65533:
        parser.error("Choose a proxy port between 1024 and 65533")
    if any((args.output / name).exists() for name in ("acceptance.json", "evidence.json")):
        parser.error("Choose a new evidence directory to preserve the previous measurements")
    runtime = Path(tempfile.mkdtemp(prefix="lf-replicas-")).resolve()
    base = f"http://127.0.0.1:{args.port}"
    state = runtime / "acceptance-state.json"
    creds = runtime / "credentials.json"
    manifest = read_json(TRIALS / "fixtures/manifest.json")
    check(manifest["source_commit"] == COMMIT, "Fixture/backend revision mismatch")
    evidence = {
        "started_utc": datetime.now(timezone.utc).isoformat(), "source_commit": COMMIT,
        "deployment": "Two Uvicorn ASGI OS processes and one HTTP round-robin proxy on the same Mac; "
                      "shared local SQLite WAL; separately invoked deterministic MCP worker",
        "runtime": {"os": platform.system(), "os_release": platform.release(), "arch": platform.machine(),
                    "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                    "uvicorn": version("uvicorn"), "mcp": version("mcp")},
        "common_runner_sha256": digest(ACCEPTANCE.read_bytes()), "inputs": manifest,
        "durations_ms": {}, "scenarios": {},
    }

    def timed(label, fn, *params):
        start = time.perf_counter()
        value = fn(*params)
        evidence["durations_ms"][label] = milliseconds(start)
        return value

    def service(action, target="all"):
        return json.loads(command(HERE / "services.py", "--runtime", runtime, "--port", str(args.port), action, target))

    def acceptance(mode):
        return json.loads(command(ACCEPTANCE, mode, "--base-url", base, "--credentials", creds, "--state", state))

    client = httpx.Client(base_url=base, headers={"Origin": base}, trust_env=False, timeout=15)
    try:
        started = timed("cold_start", service, "start")
        active = pids(started)
        check(set(active) == {"a", "b", "proxy"} and None not in active.values()
              and len(set(active.values())) == 3, "Expected three distinct serving processes")
        evidence["initial_pids"] = active
        source = runtime / "source/lab-factory"
        actual_hashes = {name: digest((source / name).read_bytes()) for name in manifest["source_file_sha256"]}
        check(actual_hashes == manifest["source_file_sha256"], "Runner input hashes differ from the Git archive")
        evidence["verified_archive_source_files"] = len(actual_hashes)
        common_run = timed("common_run", acceptance, "run")
        credentials = read_json(creds)
        # HTTP loopback only. The backend issues a Secure reviewer cookie for HTTPS.
        login = client.post("/api/login", json={"name": "Reviewer", "password": credentials["password"]})
        login.raise_for_status()
        client.headers["Cookie"] = "__Host-labfactory-review=" + login.cookies["__Host-labfactory-review"]
        fixture = read_json(TRIALS / "fixtures/workload.json")
        new_order = client.post("/api/analysis/orders", json=fixture["examples"]["density"]).raise_for_status().json()
        order = new_order["id"]
        path = "/api/analysis/orders/" + order
        directory = runtime / "worker-artifacts"
        command(HERE / "worker.py", "prepare", "--artifact-dir", directory)
        token = runtime / "worker-token"
        with os.fdopen(os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            file.write(credentials["tokens"][AGENT])
        worker_args = ["process", "--base-url", base, "--order", order, "--worker", AGENT,
                       "--token-file", token, "--artifact-dir", directory, "--case", "density"]
        killed = claim_and_interrupt(worker_args, list(active.values()))
        before = [read_order(client, path)[1] for _ in range(4)]
        alternate(before)
        check(all(x["status"] == "in_progress" and x["submissions"] == 0 for x in before),
              "Interrupted claim/submission boundary changed")
        after_loss = pids(timed("stop_replica_a", service, "stop", "a"))
        check(after_loss == active | {"a": None} and listener_down(args.port + 1), "Replica A did not stop")
        failover = [read_order(client, path)[1] for _ in range(4)]
        check(all(x["replica"] == "b" for x in failover), "Read did not fail over")
        db = Path(started["database"])
        db_before = database_info(db)
        stopped = pids(timed("stop_remaining_services", service, "stop"))
        check(all(pid is None for pid in stopped.values()) and all(listener_down(args.port + i) for i in range(3)),
              "A service stayed online")
        timed("common_offline", acceptance, "offline")
        restored = timed("restore_services", service, "start")
        replacement = pids(restored)
        check(len(set(replacement.values())) == 3 and None not in replacement.values()
              and set(active.values()).isdisjoint(replacement.values()), "Expected distinct replacement processes")
        check(Path(restored["database"]) == db, "Restored services use a different DB path")
        db_after = database_info(db)
        check(db_after == db_before, "Database identity changed")
        resumed_reads = [read_order(client, path)[1] for _ in range(4)]
        alternate(resumed_reads)
        check(len({x["body_sha256"] for x in before + failover + resumed_reads}) == 1,
              "Order contents differed across outage or restart")
        final_common = timed("common_verify_after_restart", acceptance, "verify")
        check(common_run["outcome_sha256"] == final_common["outcome_sha256"], "Common result fingerprint changed")
        rows = timed("replacement_worker_start_to_exit", command, HERE / "worker.py", *worker_args)
        resumed, submitted = [json.loads(line) for line in rows.splitlines()]
        check(resumed["action"] == "resumed" and submitted["passed"] and submitted["submission"] == 1
              and submitted["status"] == "in_review" and submitted["worker_pid"] != killed["marker"]["worker_pid"]
              and submitted["artifact_digest"] == manifest["artifact_sha256"]["density"],
              "Replacement worker did not resume the original claim and submit the fixed artifact")
        replay = json.loads(command(HERE / "worker.py", *worker_args))
        check(replay["event"] == "already_submitted", "Worker failed to recognize completed submission")
        detail, _ = read_order(client, path)
        claims = [r for r in detail["history"] if r["event"] == "claimed"]
        check(len(claims) == len(detail["submissions"]) == 1 and claims[0]["actor"] == AGENT,
              "Unexpected claim or submission count")
        client.post(f"/api/orders/{order}/approve", json={"submission": 1}).raise_for_status()
        receipt = client.post(path + "/runs", json={"submission": 1}).raise_for_status().json()
        values = [row["value"] for row in receipt["results"]]
        check(values == [1.08, 0.8] and receipt["control"]["passed"] and receipt["worker"] == AGENT,
              "Recovery job receipt changed")

        evidence["scenarios"] = {
            "two_replica_reads": {"passed": True, "samples": before},
            "one_replica_down": {"passed": True, "pids": after_loss, "a_listener_refused": True, "samples": failover},
            "full_service_restart": {"passed": True, "all_offline_pids": stopped, "new_pids": replacement,
                                     "database_before": db_before, "database_after": db_after, "samples": resumed_reads},
            "interrupted_worker": {"passed": True, "order": order, "identity": AGENT, "terminated": killed,
                                   "resumed": resumed, "submitted": submitted, "replayed": replay,
                                   "claim_events": len(claims), "numbered_submissions": len(detail["submissions"]),
                                   "control_passed": receipt["control"]["passed"], "values": values, "unit": receipt["unit"]},
        }
        common = read_json(state)
        check(common["verification"]["passed"] and common["downtime"]["confirmed"], "Missing restart evidence")
        # Each of these gates is required by exercise(), observe(), ready(), offline or verify
        # in the byte-identified common runner. A failed gate exits before evidence is published.
        evidence["common_scenarios"] = dict.fromkeys((
            "named_reviewer_and_separate_mcp_identities",
            "unauthenticated_mcp_denied_and_four_expected_tools_available",
            "original_uploads_and_candidate_artifacts_match_fixture_bytes",
            "incorrect_candidate_passes_authored_tests_and_fails_blind_control",
            "failed_candidate_approval_and_run_denied",
            "used_control_cannot_be_retried_until_replaced",
            "stale_submission_approval_denied_and_exact_release_digest_approved",
            "released_caffeine_and_density_estimates_match_expected_values",
            "saved_run_replay_and_original_csv_retrieval",
            "two_simultaneous_claims_yield_one_durable_winner",
            "full_outage_observed_and_canonical_outcome_recovered",
        ), "passed")
        evidence["common"] = {k: common[k] for k in (
            "access_mode", "workload_sha256", "request_sequence_sha256", "outcome_sha256", "downtime", "verification")}
        evidence["limitations"] = [
            "Same-host local filesystem only. SQLite WAL needs local shared memory and permits one writer at a time.",
            "The proxy, physical host and disk are single points of failure. No external SQL service or hosted staging was used.",
            "Worker death was injected after confirmed claim and before submission. Recovery explicitly uses the same identity and target order.",
            "The deterministic author replays the supplied candidate. The trial does not measure generation or queue throughput.",
            "Times are single observations on loopback, including client and process overhead.",
        ]
    finally:
        client.close()
        final = pids(service("stop"))
        check(all(pid is None for pid in final.values()) and all(listener_down(args.port + i) for i in range(3)),
              f"Could not confirm cleanup; retained runtime at {runtime}")
        shutil.rmtree(runtime)
    evidence["cleanup"] = {"all_listeners_down": True, "private_runtime_removed": not runtime.exists()}
    args.output.mkdir(exist_ok=True, parents=True)
    for name, value in (("acceptance.json", common), ("evidence.json", evidence)):
        (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": "passed", "outcome_sha256": common["outcome_sha256"], "cleanup": evidence["cleanup"]}))


if __name__ == "__main__":
    main()
