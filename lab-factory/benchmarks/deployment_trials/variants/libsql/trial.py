"""Exercise the pinned API and official sqld in independent, disposable processes."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import io
import ipaddress
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import NameOID

from provision_engine import ARCHIVE_SHA256, BINARY_SHA256, RELEASE, verify

HERE = Path(__file__).resolve().parent
TRIALS = HERE.parent.parent
REPO = TRIALS.parents[2]
RUNNER = TRIALS / "acceptance.py"
COMMIT = "62badef1d608d94903da475bfd2b689cb80f9c49"
LOOPBACK = "127.0.0.1"


def elapsed(start):
    return round((time.perf_counter() - start) * 1000, 2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sql_snapshot(proc, path, number):
    proc.send_signal(signal.SIGUSR1)
    deadline = time.perf_counter() + 3
    while time.perf_counter() < deadline:
        if path.exists():
            counts = json.loads(path.read_bytes())
            if counts["snapshot_number"] == number:
                return counts
        time.sleep(0.01)
    raise RuntimeError("SQL request counter snapshot timed out")


def make_keys(root):
    """Create trial-only TLS material and an Ed25519 token accepted by sqld itself."""
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable SQL trial")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, LOOPBACK)])
    ca_key = ec.generate_private_key(ec.SECP256R1())
    tls_key = ec.generate_private_key(ec.SECP256R1())

    def cert(subject, key, is_ca):
        builder = (x509.CertificateBuilder().issuer_name(name).subject_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.KeyUsage(True, False, False, False, False, is_ca, is_ca, False, False),
                                  critical=True))
        if not is_ca:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(LOOPBACK))]), critical=False)
        return builder.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)

    (root / "ca.pem").write_bytes(cert(name, ca_key, True))
    (root / "server.pem").write_bytes(cert(leaf_name, tls_key, False))
    (root / "server.key").write_bytes(tls_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    db_key = ed25519.Ed25519PrivateKey.generate()
    (root / "db-auth.pub").write_bytes(db_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return jwt.encode({"a": "rw", "exp": now + timedelta(hours=1)}, db_key, algorithm="EdDSA")


def ports(count):
    with ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(count)]
        for sock in sockets:
            sock.bind((LOOPBACK, 0))
        return [sock.getsockname()[1] for sock in sockets]


def stop(process, *, crash=False):
    if process.poll() is None:
        if crash:
            process.kill()
        else:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return process.returncode


def await_http(process, url, path, headers=None, timeout=18):
    start = time.perf_counter()
    with httpx.Client(base_url=url, headers=headers, trust_env=False, timeout=1) as client:
        while time.perf_counter() - start < timeout:
            if process.poll() is not None:
                raise RuntimeError(f"Process exited with {process.returncode} before {path} came up")
            try:
                if client.get(path).status_code == 200:
                    return elapsed(start)
            except httpx.TransportError:
                pass
            time.sleep(0.025)
    raise RuntimeError(f"Readiness timed out for {path}")


def execute_trial(binary, root, stack):
    manifest = json.loads((TRIALS / "fixtures/manifest.json").read_bytes())
    fixture = json.loads((TRIALS / "fixtures/workload.json").read_bytes())
    if manifest["source_commit"] != COMMIT:
        raise ValueError("Workload and backend commit differ")
    runner_hash = sha(RUNNER)
    binary = binary.resolve()
    verify(binary, BINARY_SHA256)
    source_paths = ["lab-factory/api", "lab-factory/src", "lab-factory/examples"]
    archive = subprocess.check_output(["git", "-C", REPO, "archive", COMMIT, *source_paths])
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(root, filter="data")
    app = root / "lab-factory"
    api_port, peer_port, sql_port, tls_port = ports(4)
    base = f"http://{LOOPBACK}:{api_port}"
    db_url = f"https://{LOOPBACK}:{tls_port}"
    clean = {"HOME": str(root), "TMPDIR": str(root), "PATH": os.defpath,
             "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(app / "src")}
    credentials = root / "credentials.json"
    state = root / "state.json"
    token = make_keys(root)
    roles = {}
    timings = {}
    processes = []

    def launch(name, cmd, env, cwd):
        log = stack.enter_context((root / (name + ".log")).open("wb"))
        proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        processes.append(proc)
        stack.callback(stop, proc)
        roles[name] = proc.pid
        return proc

    def runner(mode, endpoint=base):
        args = [sys.executable, RUNNER, mode, "--credentials", credentials, "--base-url", endpoint]
        if mode == "env":
            args.append("--private")
        if mode in ("run", "offline", "verify"):
            args += ["--state", state]
        start = time.perf_counter()
        result = subprocess.run(args, env=clean, cwd=root, capture_output=True, text=True, timeout=240)
        ms = elapsed(start)
        if result.returncode:
            raise RuntimeError(f"Acceptance {mode} failed: {result.stderr.strip()[:900]}")
        return result.stdout.strip(), ms

    runner("credentials")
    reviewer_env = json.loads(runner("env")[0])
    def start_sql(name, image_dir):
        return launch(name, [binary, "--no-welcome", "--http-listen-addr", f"{LOOPBACK}:{sql_port}",
                      "--db-path", image_dir, "--auth-jwt-key-file", root / "db-auth.pub"], clean, root)

    def start_api(name, port):
        work = root / name
        work.mkdir()
        env = {**clean, **reviewer_env, "LABFACTORY_PUBLIC_ORIGIN": f"http://{LOOPBACK}:{port}",
               "TURSO_DATABASE_URL": db_url, "TURSO_AUTH_TOKEN": token, "SSL_CERT_FILE": str(root / "ca.pem")}
        return launch(name, [sys.executable, "-m", "uvicorn", "api.index:app", "--app-dir", app,
                             "--host", LOOPBACK, "--port", str(port), "--workers", "1",
                             "--no-access-log", "--log-level", "warning"], env, work)

    original_db = root / "data.sqld"
    sql = start_sql("sql_initial", original_db)
    upstream = f"http://{LOOPBACK}:{sql_port}"
    await_http(sql, upstream, "/health")
    # Authentication is enforced by the database even when the TLS proxy is bypassed on loopback.
    probe = {"requests": [{"type": "get_autocommit"}, {"type": "close"}]}
    with httpx.Client(base_url=upstream, trust_env=False) as upstream_client:
        denied = upstream_client.post("/v3/pipeline", json=probe).status_code
        accepted = upstream_client.post("/v3/pipeline", json=probe,
                                        headers={"Authorization": "Bearer " + token}).status_code
    if denied not in (401, 403) or accepted != 200:
        raise RuntimeError(f"Native SQL bearer gate failed ({denied}, {accepted})")

    proxy = launch("sql_tls", [sys.executable, HERE / "tls_proxy.py", "--port", str(tls_port),
                   "--upstream-port", str(sql_port), "--cert", root / "server.pem", "--key", root / "server.key",
                   "--stats", root / "stats.json"], {**clean, "TURSO_AUTH_TOKEN": token}, root)

    cold = time.perf_counter()
    api = start_api("api_initial", api_port)
    await_http(api, base, "/api/session")
    with httpx.Client(base_url=base, trust_env=False) as client:
        denied_reviewer = client.get("/api/orders").status_code
        if denied_reviewer != 401:
            raise RuntimeError("Private reviewer gate failed")
        login = client.post("/api/login", headers={"Origin": base},
                            json={"name": "Reviewer", "password": json.loads(credentials.read_bytes())["password"]})
        login.raise_for_status()
        # Apply the same explicit loopback-only Secure cookie handling as the shared runner.
        cookie_name = "__Host-labfactory-review"
        reviewer_headers = {"Cookie": f"{cookie_name}={login.cookies[cookie_name]}"}
    await_http(api, base, "/api/orders", reviewer_headers)
    timings["initial_api_spawn_to_database_backed_read_ms"] = elapsed(cold)
    before = sql_snapshot(proxy, root / "stats.json", 1)
    _, timings["acceptance_run_ms"] = runner("run")
    after = sql_snapshot(proxy, root / "stats.json", 2)
    common_sql = {p: count - before["by_path"].get(p, 0) for p, count in after["by_path"].items()}
    original_state = json.loads(state.read_bytes())
    initial_sql_pid = sql.pid
    crash_start = time.perf_counter()
    stop(api, crash=True)
    _, timings["acceptance_offline_ms"] = runner("offline")
    spawn_time = time.perf_counter()
    replacement = start_api("api_replacement", api_port)
    await_http(replacement, base, "/api/orders", reviewer_headers)
    timings["replacement_api_spawn_to_database_backed_read_ms"] = elapsed(spawn_time)
    timings["api_kill_to_database_backed_read_including_offline_probe_ms"] = elapsed(crash_start)
    if sql.poll() is not None or sql.pid != initial_sql_pid:
        raise RuntimeError("SQL process changed during API replacement")
    _, timings["acceptance_verify_after_api_replacement_ms"] = runner("verify")
    verified_on_replacement = json.loads(state.read_bytes())["verification"]

    # Both API processes remain alive while the same released order is read on each port.
    peer = start_api("api_peer", peer_port)
    peer_url = f"http://{LOOPBACK}:{peer_port}"
    await_http(peer, peer_url, "/api/orders", reviewer_headers)
    order_path = "/api/analysis/orders/" + original_state["ids"]["caffeine"]
    with httpx.Client(headers=reviewer_headers, trust_env=False) as client:
        primary_data = client.get(base + order_path).raise_for_status().json()
        peer_data = client.get(peer_url + order_path).raise_for_status().json()
        if primary_data != peer_data or primary_data["order"]["status"] != "released":
            raise RuntimeError("API workers returned different released order data")
        db_crash = time.perf_counter()
        stop(sql, crash=True)
        observe_time = time.perf_counter()
        unavailable = client.get(base + "/api/orders")
        timings["storage_outage_request_ms"] = elapsed(observe_time)
        session_status = client.get(base + "/api/session").status_code
        if unavailable.status_code != 503 or session_status != 200:
            raise RuntimeError(f"Unexpected SQL outage statuses ({unavailable.status_code}, {session_status})")
        start_new_sql = time.perf_counter()
        reopened = start_sql("sql_reopened", original_db)
        await_http(replacement, base, "/api/orders", reviewer_headers)
        timings["sql_respawn_to_database_backed_read_ms"] = elapsed(start_new_sql)
        timings["sql_kill_to_database_backed_read_including_probes_ms"] = elapsed(db_crash)
        if peer.poll() is not None or replacement.poll() is not None or reopened.poll() is not None:
            raise RuntimeError("A worker or the database exited during recovery")
    _, timings["acceptance_verify_after_sql_restart_ms"] = runner("verify")
    verified_on_reopened = json.loads(state.read_bytes())["verification"]
    from backup import cold_backup
    restore_start = time.perf_counter()
    if stop(reopened) != 0:
        raise RuntimeError("Cold backup requires a clean database shutdown")
    restored_db = root / "restored.sqld"
    backup_evidence = cold_backup(original_db, root / "backup.sqld", restored_db)
    restored = start_sql("sql_restored", restored_db)
    await_http(replacement, base, "/api/orders", reviewer_headers)
    timings["cold_backup_and_restore_stop_to_database_backed_read_ms"] = elapsed(restore_start)
    _, timings["acceptance_verify_after_cold_restore_ms"] = runner("verify")
    final_state = json.loads(state.read_bytes())
    if runner_hash != sha(RUNNER) or not final_state["verification"]["passed"]:
        raise RuntimeError("Runner changed during trial or recovery failed")
    # This extra work order is created only after the shared fingerprint has been reverified.
    from peer_probe import cross_worker_claim
    peer_claim = cross_worker_claim(base, peer_url, credentials)
    from analysis_worker_probe import run_probe
    author_recovery = run_probe(base, credentials, root, clean)
    for proc in (peer, replacement, restored, proxy):
        stop(proc)
    stats = json.loads((root / "stats.json").read_bytes())
    db_files = sorted(p for p in (root / "data.sqld").rglob("*") if p.is_file())
    image = [(p.relative_to(root / "data.sqld").as_posix(), p.stat().st_size) for p in db_files]
    api_files = {name: sorted(p.name for p in (root / name).iterdir())
                 for name in ("api_initial", "api_replacement", "api_peer")}
    return {
        "deployment_type": "Local stateless ASGI API + independent official libSQL sqld over TLS/Hrana v3",
        "hosted_preview": {"status": "unverified", "reason": "No dedicated, authorized hosted credentials or preview supplied."},
        "engine": {"classification": "official self-hosted libSQL sqld", "version": subprocess.check_output(
            [binary, "--version"], text=True).strip(), "archive_sha256": ARCHIVE_SHA256, "binary_sha256": BINARY_SHA256,
            "source": RELEASE.rsplit("/download/", 1)[0] + "/tag/libsql-server-v0.24.32",
            "native_jwt_without_token_http": denied, "native_jwt_with_token_http": accepted},
        "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine(),
                 "python": platform.python_version(), "packages": {p: importlib.metadata.version(p)
                 for p in ("uvicorn", "httpx", "mcp", "turso-serverless", "cryptography", "PyJWT")}},
        "source_commit": COMMIT, "backend_entry_point": "api.index:app",
        "storage_path": "labfactory.hosted_storage.run_store -> turso_serverless.Connection -> HTTPS Hrana",
        "hosted_local_db_or_blob_environment_set": False,
        "acceptance_runner_sha256": runner_hash, "inputs": manifest, "acceptance": final_state,
        "reviewer_gate_without_session_http": denied_reviewer,
        "cold_backup_restore": backup_evidence, "analysis_worker_recovery": author_recovery,
        "candidate_source_utf8_sha256": {k: hashlib.sha256(v["source"].encode()).hexdigest()
                                        for k, v in fixture["artifacts"].items()},
        "fresh_control_canonical_json_sha256": hashlib.sha256(json.dumps(fixture["fresh_control"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        "acceptance_run_sql_posts_by_path": common_sql,
        "acceptance_run_failed_sql_http_requests": after["failed_requests"] - before["failed_requests"],
        "acceptance_scenarios": dict.fromkeys([
            "unauthenticated MCP denied", "two worker identities initialize and list four tools",
            "intake caffeine and density", "author receives protocol without expected held-back control",
            "wrong candidate passes its own tests and fails independent control",
            "reject approval and execution of failed revision", "require fresh control after failed submission",
            "verify corrected caffeine and density candidates", "reject stale approval",
            "approve exact submission and digest", "correct two numerical results for each analysis",
            "protocol and readings round-trip with pinned SHA256", "preserve receipt and original on replay",
            "two simultaneous worker claims produce one persisted winner", "API offline confirmed",
            "replacement API reproduces canonical outcome", "restarted SQL reproduces canonical outcome",
            "cold backup restored into a fresh directory reproduces canonical outcome", "named reviewer gate and login",
        ], "pass"),
        "timings_ms": timings, "process_ids": roles, "proxy_stats": stats, "db_file_sizes_after_shutdown": dict(image),
        "operational_checks": {
            "api_kill_signal": "SIGKILL", "api_work_dirs_after_run": api_files,
            "sql_pid_alive_across_api_restart": True, "distinct_live_api_workers_same_released_order": True,
            "sql_kill_signal": "SIGKILL", "api_workers_alive_across_sql_restart": True,
            "database_backed_read_with_sql_down_http": unavailable.status_code,
            "api_session_with_sql_down_http": session_status,
            "order_counts_verified": len(final_state["ids"]), "supplemental_cross_worker_claim": peer_claim,
            "fingerprint_after_api_restart": verified_on_replacement["outcome_sha256"],
            "fingerprint_after_sql_restart": verified_on_reopened["outcome_sha256"],
            "fingerprint_after_cold_restore": final_state["verification"]["outcome_sha256"],
            "all_child_processes_reaped": all(p.poll() is not None for p in processes)
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqld", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=1, help="number of independent fresh deployments")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    results = []
    for _ in range(args.samples):
        with tempfile.TemporaryDirectory(prefix="lab-sql-deployment-") as scratch:
            with ExitStack() as stack:
                result = execute_trial(args.sqld, Path(scratch), stack)
        result["operational_checks"]["scratch_removed"] = not Path(scratch).exists()
        results.append(result)
    primary = results[0]
    fingerprint = primary["acceptance"]["outcome_sha256"]
    if any(r["acceptance"]["outcome_sha256"] != fingerprint for r in results):
        raise RuntimeError("Fresh deployments produced different outcomes")
    primary["samples"] = [{
        "sample": i, "timings_ms": r["timings_ms"], "operational_checks": r["operational_checks"],
        "process_ids": r["process_ids"], "proxy_stats": r["proxy_stats"],
        "acceptance_run_sql_posts_by_path": r["acceptance_run_sql_posts_by_path"],
        "acceptance_run_failed_sql_http_requests": r["acceptance_run_failed_sql_http_requests"],
        "request_sequence_sha256": r["acceptance"]["request_sequence_sha256"],
        "outcome_sha256": r["acceptance"]["outcome_sha256"], "workload_sha256": r["acceptance"]["workload_sha256"],
        "acceptance_runner_sha256": r["acceptance_runner_sha256"],
        "verification": r["acceptance"]["verification"], "downtime": r["acceptance"]["downtime"],
        "cold_backup_restore": r["cold_backup_restore"], "analysis_worker_recovery": r["analysis_worker_recovery"],
    } for i, r in enumerate(results, 1)]
    write_json(args.output, primary)
    print(json.dumps({"samples_passed": len(results), "outcome_sha256": fingerprint}))


if __name__ == "__main__":
    main()
