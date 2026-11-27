"""Measure the pinned Vercel backend against a disposable loopback Blob store."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from zipfile import ZipFile

import httpx

from backup import digest, make_backup, restore_backup
from worker_recovery import probe as probe_author_recovery


HERE = Path(__file__).resolve().parent
RUNNER = HERE.parents[1] / "acceptance.py"
LAB = RUNNER.parents[2]
PYTHON = LAB / ".venv/bin/python"
COMMIT = "62badef1d608d94903da475bfd2b689cb80f9c49"


def archive_source(destination):
    raw = subprocess.check_output(["git", "archive", "--format=zip", COMMIT, "lab-factory"], cwd=LAB.parent)
    with ZipFile(io.BytesIO(raw)) as archive:
        archive.extractall(destination)
    return destination / "lab-factory"


def fresh_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_ready(process, url, verify=True):
    deadline = time.monotonic() + 20
    with httpx.Client(timeout=1, verify=verify, trust_env=False) as client:
        while process.poll() is None and time.monotonic() < deadline:
            try:
                if client.get(url + "/api/session").status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.025)
    raise RuntimeError(f"API worker did not start (exit {process.poll()})")


def event_summary(path):
    counts = Counter()
    sizes = Counter()
    for line in path.read_text().splitlines():
        event = json.loads(line)
        group = f"{event['object_type']}_{event['method']}_{event['status']}"
        counts[group] += 1
        sizes[group] += event["object_bytes"]
    return {"requests": dict(sorted(counts.items())), "successful_payload_bytes": dict(sorted(sizes.items()))}


def tls_auth(base, trust, creds):
    with httpx.Client(base_url=base, headers={"Origin": base}, verify=trust, trust_env=False) as client:
        denied = client.get("/api/orders")
        login = client.post("/api/login", json={"name": "Reviewer", "password": creds["password"]})
        orders = client.get("/api/orders")
        secure = any(c.secure and c.name == "__Host-labfactory-review" for c in client.cookies.jar)
        if (denied.status_code, login.status_code, orders.status_code) != (401, 200, 200) or not secure:
            raise ValueError("Named reviewer authentication through the TLS entry point failed")
        return {"status": "pass", "vercel": "1", "certificate_verified": True, "secure_cookie_returned": secure,
                "anonymous_order_list_status": denied.status_code, "authenticated_order_list_status": orders.status_code}


def two_workers(source, base, second_base, credentials):
    # Reuse the independent driver's actual API/MCP clients on two app processes.
    sys.path.insert(0, str(source / "src"))
    spec = importlib.util.spec_from_file_location("comparison_acceptance", RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    with ExitStack() as stack:
        clients = [runner.Wire(b, credentials, True) for b in (base, second_base)]
        for wire in clients:
            stack.callback(wire.client.close)
        order = clients[0].exchange("/api/example", {}, 201).json()["id"]
        gate = threading.Barrier(2)

        def claim(index):
            gate.wait(timeout=5)
            return runner.claim(clients[index], runner.WORKERS[index], order)

        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(claim, range(2)))
        winner = [i for i, row in enumerate(answers) if row.get("status") == "in_progress"]
        if len(winner) != 1 or sum("error" in row for row in answers) != 1:
            raise ValueError("Cross-process claim did not choose one worker")
        for wire in clients:
            state = wire.exchange("/api/orders/" + order).json()
            events = [e for e in state["history"] if e["event"] == "claimed"]
            if len(events) != 1 or events[0]["actor"] != state["order"]["worker"] or events[0]["actor"] != runner.WORKERS[winner[0]]:
                raise ValueError("API workers disagree on the durable claim")
    return {"status": "pass", "api_processes": 2, "mcp_identities": 2, "winning_responses": 1,
            "losing_responses": 1, "persisted_claim_events": 1, "read_confirmed_by_both_processes": True}


def run(tmp, timings):
    def measure(name, callback, *args):
        start = time.perf_counter()
        value = callback(*args)
        timings[name] = round(time.perf_counter() - start, 4)
        return value

    source = archive_source(tmp)
    env = {"PATH": os.defpath, "TMPDIR": str(tmp), "PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    runner_hash = digest(RUNNER.read_bytes())
    manifest = json.loads((RUNNER.parent / "fixtures/manifest.json").read_bytes())
    if manifest["source_commit"] != COMMIT or any(digest((source / f).read_bytes()) != h for f, h in manifest["source_file_sha256"].items()):
        raise ValueError("Runner input manifest does not match Git archive")
    port = fresh_port()
    base = f"http://127.0.0.1:{port}"
    creds = tmp / "credentials.json"
    state = tmp / "state.json"

    def acceptance(mode):
        command = [PYTHON, "-B", RUNNER, mode, "--base-url", base, "--credentials", creds, "--private"]
        if mode in {"run", "offline", "verify"}:
            command.extend(["--state", state])
        result = subprocess.run(command, cwd=tmp, env=env, stdout=subprocess.PIPE, check=True, timeout=180)
        return None if mode == "credentials" else json.loads(result.stdout)

    acceptance("credentials")
    app_env = env | acceptance("env")
    token = "vercel_blob_rw_trial_" + secrets.token_urlsafe(32)
    restored_token = "vercel_blob_rw_trial_" + secrets.token_urlsafe(32)
    sidecar_env = {"PATH": os.defpath, "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1"}
    with ExitStack() as stack:
        def sidecar(directory, secret):
            process = subprocess.Popen([PYTHON, "-B", HERE / "blob_sidecar.py", "--directory", directory,
                                        "--events", tmp / (directory.name + ".jsonl")], stdout=subprocess.PIPE,
                                       cwd=tmp, env=sidecar_env | {"BLOB_READ_WRITE_TOKEN": secret})
            stack.callback(stop, process)
            return process, json.loads(process.stdout.readline())["port"]

        def worker(listen_port, blob_port, secret, trust=None):
            tls_args = ["--tls-cert", tmp / "localhost.crt", "--tls-key", tmp / "localhost.key"] if trust else []
            process = subprocess.Popen([PYTHON, "-B", HERE / "worker.py", "--source-root", source, "--port", str(listen_port),
                                        "--blob-port", str(blob_port), *tls_args], cwd=tmp, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, env=app_env | {"BLOB_READ_WRITE_TOKEN": secret})
            stack.callback(stop, process)
            scheme = "https" if trust else "http"
            wait_ready(process, f"{scheme}://127.0.0.1:{listen_port}", trust or True)
            return process

        storage, blob_port = measure("first_store_start", sidecar, tmp / "first-store", token)
        first = measure("first_worker_start_until_session_ready", worker, port, blob_port, token)
        initial = measure("acceptance_run", acceptance, "run")
        run_traffic = event_summary(tmp / "first-store.jsonl")
        stop(first)
        measure("stopped_worker_offline_check", acceptance, "offline")
        second = measure("replacement_worker_start_until_session_ready", worker, port, blob_port, token)
        restart_check = measure("acceptance_verify_after_worker_restart", acceptance, "verify")
        if first.pid == second.pid:
            raise ValueError("Worker process did not change")
        stop(second)
        measure("pre_restore_offline_check", acceptance, "offline")
        backup = measure("backup_snapshot_and_originals", make_backup, tmp / "backup", blob_port, token)
        first_traffic = event_summary(tmp / "first-store.jsonl")
        stop(storage)
        restored_store, restored_port = measure("empty_store_start", sidecar, tmp / "restored-store", restored_token)
        measure("restore_objects_and_check_snapshot", restore_backup, tmp / "backup", backup, restored_port, restored_token)
        third = measure("restored_worker_start_until_session_ready", worker, port, restored_port, restored_token)
        restored_check = measure("acceptance_verify_after_empty_store_restore", acceptance, "verify")
        recovered = make_backup(tmp / "readback", restored_port, restored_token)
        if backup != recovered or len({first.pid, second.pid, third.pid}) != 3 or storage.pid == restored_store.pid:
            raise ValueError("Full restore or process replacement check failed")
        restored_traffic = event_summary(tmp / "restored-store.jsonl")
        alt_port = fresh_port()
        worker(alt_port, restored_port, restored_token)
        pair = measure("supplemental_cross_process_claim", two_workers, source, base, f"http://127.0.0.1:{alt_port}", json.loads(creds.read_text()))
        total = event_summary(tmp / "restored-store.jsonl")
        pair["snapshot_precondition_failures"] = total["requests"].get("snapshot_PUT_412", 0) - restored_traffic["requests"].get("snapshot_PUT_412", 0)
        fixture = json.loads((RUNNER.parent / "fixtures/workload.json").read_bytes())
        author_recovery = measure("supplemental_author_crash_and_resume", probe_author_recovery, source, base, json.loads(creds.read_text()), fixture)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", tmp / "localhost.key", "-out", tmp / "localhost.crt"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        trust = ssl.create_default_context(cafile=tmp / "localhost.crt")
        tls_port = fresh_port()
        worker(tls_port, restored_port, restored_token, trust)
        tls = tls_auth(f"https://127.0.0.1:{tls_port}", trust, json.loads(creds.read_bytes()))

    final = json.loads(state.read_bytes())
    if digest(RUNNER.read_bytes()) != runner_hash or any(item["outcome_sha256"] != final["outcome_sha256"] for item in (initial, restart_check, restored_check)):
        raise ValueError("Runner or canonical outcome changed")
    observations = {name: {"approved_submission": result["approval"]["submission"], "values": result["values"],
                           "unit": result["unit"], "uploads_sha256": result["uploads"],
                           "submissions": [{"number": s["number"], "artifact_sha256": s["artifact_sha256"],
                                            "blind_control_passed": s["control"]["passed"], "control_edition": s["control"]["edition"]}
                                           for s in result["submissions"]], "replayed_same_receipt": result["replayed_receipt"]}
                    for name, result in final["outcome"].items() if name in ("caffeine", "density")}
    return {"variant": "vercel_blob", "tested_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": COMMIT,
            "deployment_type": "Local loopback HTTP, pinned Vercel Python ASGI entrypoint under uvicorn, private Blob HTTP sidecar",
            "live_vercel_preview": {"status": "unverified", "reason": "Local fallback uses disposable loopback storage. Pinned adapter requires a separately provisioned private Blob read/write token for live staging."},
            "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "system": platform.system(),
                            "architecture": platform.machine(), "access_mode": final["access_mode"], "vercel_env": "preview"},
            "runner_sha256": runner_hash, "inputs": manifest, "candidate_source_sha256": {
                name: digest(candidate["source"].encode()) for name, candidate in fixture["artifacts"].items()},
            "acceptance": final, "canonical_outcome_sha256": final["outcome_sha256"],
            "run_request_sequence_sha256": final["request_sequence_sha256"], "runner_phases": {"run": initial, "offline": final["downtime"],
                "verify_replacement_worker": restart_check, "verify_restored_store": restored_check},
            "acceptance_scenarios": {s: "pass" for s in ("named_reviewer_login", "mcp_auth_and_tool_discovery", "caffeine_and_density_intake",
                "caffeine_bad_candidate_failed_blind_control", "failed_or_stale_approval_and_run_blocked", "fresh_control_required_and_replaced",
                "caffeine_and_density_release", "exact_candidate_protocol_csv_and_receipt_provenance", "expected_values_and_units",
                "replay_returns_same_receipt", "two_agent_claim_single_winner", "api_offline", "cold_worker_recovery", "empty_store_backup_restore")},
            "analytical_results": observations, "canonical_outcome": final["outcome"], "shared_runner_claim_race": final["outcome"]["race"],
            "supplemental_two_process_claim": pair, "supplemental_author_crash_recovery": author_recovery, "supplemental_tls_login": tls,
            "retained": backup, "restore": {"original_api_process_exited": True, "original_storage_process_exited": True,
                "empty_new_store_and_new_token": True, "backup_and_readback_manifests_identical": True},
            "blob_traffic": {"acceptance_run_only": run_traffic, "run_plus_worker_restart_verify_plus_backup": first_traffic,
                             "restore_plus_verify_plus_readback": restored_traffic},
            "limitations": ["No live Vercel build, function scheduler, edge routing, authentication, CDN or Blob service measurements.",
                            "One local synthetic workload. Time includes runner process startup, authentication, and loopback I/O.",
                            "Whole SQLite object replaced on changed transactions; 8 MiB cap, four CAS attempts, separate immutable uploads.",
                            "ETags identify the current object; prior snapshots require independent backups."], "elapsed_seconds": timings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    timings = {}
    with tempfile.TemporaryDirectory(prefix="lab-blob-trial-") as temp:
        result = run(Path(temp), timings)
    timings["end_to_end_with_cleanup"] = round(time.perf_counter() - started, 4)
    result["cleanup"] = "All child processes exited and private temporary storage, log, credential and backup files removed."
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "pass", "outcome_sha256": result["canonical_outcome_sha256"], "elapsed_seconds": timings}, indent=2))


if __name__ == "__main__":
    main()
