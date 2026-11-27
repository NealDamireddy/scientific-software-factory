"""Run the common deployment trial and the single-host recovery checks over loopback."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib


HERE = Path(__file__).resolve().parent
COMMON = HERE.parents[1]
PROJECT = COMMON.parents[1]
RUNNER = COMMON / "acceptance.py"
PYTHON = PROJECT / ".venv/bin/python"
PIN = "62badef1d608d94903da475bfd2b689cb80f9c49"
CLEAN_ENV = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}


def require(test, message):
    if not test:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(script, *args, env=None, output_json=True):
    result = subprocess.run([str(PYTHON), str(script), *map(str, args)], cwd=PROJECT,
                            env={**CLEAN_ENV, **(env or {})}, text=True, capture_output=True,
                            timeout=150, check=False)
    if result.returncode:
        # The configuration subcommand emits private material to stdout.
        raise RuntimeError(f"{script.name} {args[0]} exited {result.returncode}: {result.stderr.strip()}")
    return json.loads(result.stdout) if output_json else None


def environment_metadata():
    packages = ("uvicorn", "starlette", "mcp", "httpx", "turso-serverless", "PyJWT")
    return {
        "system": platform.system(), "os_version": platform.mac_ver()[0] or platform.release(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "packages": {package: importlib.metadata.version(package) for package in packages},
    }


def check_package(package, manifest):
    for relative, expected in manifest["source_file_sha256"].items():
        require(digest(package / relative) == expected, f"Fixture source mismatch in archive: {relative}")
    lock = tomllib.loads((package / "uv.lock").read_text())
    locked = {p["name"]: p["version"] for p in lock["package"]}
    for name, version in environment_metadata()["packages"].items():
        require(locked[name.lower()] == version, f"{name} differs from the pinned dependency lock")


def scenario_status(state):
    """Report individual shared assertions after the run and all verification phases return zero."""
    outcome = state["outcome"]
    coffee, liquid = outcome["caffeine"], outcome["density"]
    observations = {
        "named_reviewer_login_and_bearer_only_mcp": state["access_mode"] == "private",
        "fixed_caffeine_candidate_passed_fresh_control": coffee["submissions"][1]["control"]["passed"],
        "wrong_candidate_rejected_by_held_back_control": not coffee["submissions"][0]["control"]["passed"],
        "fresh_control_required_after_failed_blind_attempt": [
            s["control"]["edition"] for s in coffee["submissions"]] == [1, 2],
        "only_passing_numbered_caffeine_submission_released": coffee["approval"]["submission"] == 2,
        "density_candidate_control_and_approval": liquid["control_passed"] and liquid["approval"]["submission"] == 1,
        "caffeine_results": coffee["values"] == [24, 45] and coffee["unit"] == "mg/L",
        "density_results": liquid["values"] == [1.08, 0.8] and liquid["unit"] == "g/mL",
        "replay_returns_original_receipts": all(outcome[n]["replayed_receipt"] for n in ("caffeine", "density")),
        "original_upload_and_archived_batch_hashes": all(
            set(outcome[n]["uploads"]) == {"protocol", "csv"} for n in ("caffeine", "density")),
        "concurrent_claim_one_durable_winner": outcome["race"] == {
            "winners": 1, "claim_events": 1, "status": "in_progress"},
        "observed_downtime_and_restored_canonical_outcome": state["downtime"]["confirmed"] and
        state["verification"]["passed"] and state["verification"]["outcome_sha256"] == state["outcome_sha256"],
    }
    require(all(observations.values()), "Shared acceptance scenario summary does not match observations")
    return {name: "passed" for name in observations}


def port_available():
    with socket.socket(socket.AF_INET) as port:
        port.bind(("127.0.0.1", 0))
        return port.getsockname()[1]


def authenticated_reads(base, credentials):
    # Reuse the shared runner's reviewer login and local Secure-cookie handling.
    sys.path.insert(0, str(COMMON))
    try:
        import acceptance
    finally:
        sys.path.pop(0)
    wire = acceptance.Wire(base, json.loads(credentials.read_text()), True)
    samples = []
    try:
        for _ in range(12):
            start = time.perf_counter()
            orders = wire.exchange("/api/orders").json()["orders"]
            samples.append(round((time.perf_counter() - start) * 1000, 3))
            require(len(orders) == 3, "Expected three canonical work orders")
    finally:
        wire.client.close()
    return {"route": "GET /api/orders", "status": 200, "orders": 3,
            "mode": "same authenticated HTTP client, sequential post-workload reads",
            "samples_ms": samples, "median_ms": round(statistics.median(samples), 3)}


def run_trial(root):
    port = port_available()
    base = f"http://127.0.0.1:{port}"
    service = HERE / "service.py"
    volume = HERE / "volume.py"
    live = root / "live"
    restored = root / "restored"
    db = live / "volume/lab.sqlite3"
    backup = root / "snapshot.sqlite3"
    recovered_db = restored / "volume/lab.sqlite3"
    credentials = root / "credentials.json"
    state = root / "state.json"
    started = datetime.now(timezone.utc).isoformat()
    timings = {}
    lifecycle = {}
    snapshots = {}
    checks = {}

    def step(label, func, *args, **kwargs):
        start = time.perf_counter()
        value = func(*args, **kwargs)
        timings[label] = round((time.perf_counter() - start) * 1000, 3)
        return value

    def phase(mode, label):
        result = step(label, checked, RUNNER, mode, "--base-url", base, "--state", state,
                      "--credentials", credentials)
        checks[label] = {"status": "passed", **result}

    def manage(action, runtime, label, env_file=None):
        options = ["--port", port] if action == "start" else []
        if env_file is not None:
            options.extend(["--env-file", env_file])
        status = step(label, checked, service, action, "--runtime", runtime, *options)
        lifecycle[label] = status
        return status

    def inspect(label, action, *paths):
        result = step(label, checked, volume, action, *paths)
        snapshots[label] = {"logical_sha256": result["logical_sha256"],
                            "integrity_check": result["integrity_check"],
                            "foreign_key_check": result["foreign_key_check"],
                            "database_bytes": paths[-1].stat().st_size,
                            "operation_ms": result["duration_ms"]}
        if label == "before_crash":
            snapshots[label].update(table_counts=result["table_counts"], table_sha256=result["table_sha256"])
        else:
            require(result["logical_sha256"] == snapshots["before_crash"]["logical_sha256"],
                    f"{label} changed the SQLite snapshot")

    manifest = json.loads((COMMON / "fixtures/manifest.json").read_text())
    fixture = json.loads((COMMON / "fixtures/workload.json").read_text())
    require(manifest["source_commit"] == PIN, "Workload does not match release")
    fresh_json = json.dumps(fixture["fresh_control"], sort_keys=True, separators=(",", ":")).encode()
    inputs = {**manifest, "runner_sha256": digest(RUNNER),
              "fresh_control_canonical_sha256": hashlib.sha256(fresh_json).hexdigest(),
              "candidate_source_sha256": {
                  k: hashlib.sha256(v["source"].encode()).hexdigest() for k, v in fixture["artifacts"].items()},
              "manifest_sha256": digest(COMMON / "fixtures/manifest.json")}
    checked(RUNNER, "credentials", "--credentials", credentials, output_json=False)
    config = checked(RUNNER, "env", "--private", "--base-url", base, "--credentials", credentials)
    require(config["LABFACTORY_PUBLIC_REVIEW"] == "0", "Trial requires named reviewer configuration")
    config_file = root / "server-env.json"
    config_file.write_text(json.dumps(config))
    try:
        first = manage("start", live, "cold_package_and_start", env_file=config_file)
        require(first["ready"], "ASGI application unavailable")
        package = live / "package/lab-factory"
        check_package(package, manifest)
        inputs["entrypoint_sha256"] = digest(package / "api/index.py")
        inputs["uv_lock_sha256"] = digest(package / "uv.lock")
        phase("run", "common_run")
        latency = authenticated_reads(base, credentials)
        inspect("before_crash", "inspect", db)
        inspect("online_backup", "backup", db, backup)
        restarted = manage("crash", live, "sigkill_to_ready")
        require(restarted["server_pid"] != first["server_pid"] and
                restarted["supervisor_pid"] == first["supervisor_pid"] and
                restarted["last_exit"] == -signal.SIGKILL, "Replacement child or SIGKILL was not observed")
        phase("verify", "verify_after_sigkill")
        inspect("after_sigkill", "inspect", db)

        manage("stop", live, "stop_for_offline_check")
        phase("offline", "common_offline")
        warm = manage("start", live, "start_existing_volume")
        require(warm["ready"] and warm["supervisor_pid"] != first["supervisor_pid"], "Supervisor not replaced")
        phase("verify", "verify_existing_volume")
        inspect("after_full_restart", "inspect", db)
        manage("stop", live, "stop_original_for_restore")

        recovered_db.parent.mkdir(mode=0o700, parents=True)
        os.chmod(restored, 0o700)
        require(not recovered_db.exists(), "Restore destination must be new")
        inspect("restore_new_volume", "restore", backup, recovered_db)
        probe_token = secrets.token_urlsafe(32)
        agents = {**json.loads(config["LABFACTORY_AGENTS"]),
                  "trial-resume-probe": hashlib.sha256(probe_token.encode()).hexdigest()}
        recovery_config = {**config, "LABFACTORY_AGENTS": json.dumps(agents)}
        recovered_config_file = root / "restored-env.json"
        recovered_config_file.write_text(json.dumps(recovery_config))
        replacement = manage("start", restored, "start_restored_volume", env_file=recovered_config_file)
        require(replacement["ready"], "Restored service unavailable")
        phase("verify", "verify_restored_volume")
        inspect("after_restored_verify", "inspect", recovered_db)
        common_state = json.loads(state.read_text())
        probe = step("worker_death_and_resume", checked, HERE / "worker_probe.py",
                     "--base-url", base, "--runtime", restored, "--credentials", credentials,
                     env={"TRIAL_PROBE_WORKER_TOKEN": probe_token})
        require(digest(RUNNER) == inputs["runner_sha256"], "Common runner changed during the trial")
        require(digest(COMMON / "fixtures/workload.json") == inputs["workload_sha256"],
                "Common fixture changed during the trial")
    finally:
        for runtime in (restored, live):
            if (runtime / "config.json").exists():
                manage("stop", runtime, f"cleanup_{runtime.name}")
    with socket.socket() as closed:
        closed.settimeout(2)
        require(closed.connect_ex(("127.0.0.1", port)) != 0, "Listener still reachable after cleanup")

    return {
        "variant": "single_host", "source_commit": PIN, "started_at_utc": started,
        "deployment": {"system": "single local host, detached POSIX supervisor and Uvicorn child",
                       "transport": "IPv4 loopback HTTP", "entrypoint": "api.index:app",
                       "storage": "private host directory, SQLite database and content-addressed uploads in SQLite",
                       "reviewer_mode": common_state["access_mode"], "cloud_vm_tested": False,
                       "environment": environment_metadata()},
        "inputs": inputs, "acceptance": common_state, "checks": checks,
        "acceptance_scenarios": scenario_status(common_state),
        "process_lifecycle": lifecycle, "sqlite_snapshots": snapshots,
        "worker_recovery": probe, "timings_ms": timings, "authenticated_reads": latency,
        "cleanup": {"services_stopped": True, "listener_closed": True},
        "limitations": ["One host, one run, one local filesystem; no rented VM, network gateway, TLS or client WAN.",
                        "No host reboot, power loss, disk loss, multi-host failover or sustained load measurement.",
                        "SIGKILL followed successful commits. No interrupted write or power-loss durability claim.",
                        "Supervisor is manually started. A supervisor or host outage requires operator restart.",
                        "Worker recovery supplied the fixed candidate. Model generation and background scheduling were unmeasured.",
                        "The backup and restored copy used separate directories on the same disk."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New sanitized evidence JSON file")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose an unused output path.")
    require(Path(sys.executable).absolute() == PYTHON, "Run this script with lab-factory/.venv/bin/python")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="labfactory-single-host-") as temp:
        evidence = run_trial(Path(temp).resolve())
    evidence["cleanup"]["private_runtime_removed"] = not Path(temp).exists()
    with args.output.open("x") as out:
        json.dump(evidence, out, indent=2, sort_keys=True, allow_nan=False)
        out.write("\n")
    print(json.dumps({"status": "passed", "outcome_sha256": evidence["acceptance"]["outcome_sha256"]}))


if __name__ == "__main__":
    main()
