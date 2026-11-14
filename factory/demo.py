"""Check the presenter laptop, then serve the live demo and its read-only fallback."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check_worker():
    if not shutil.which("codex"):
        raise RuntimeError("Install the Codex CLI on the presenter laptop, then run codex login")
    try:
        subprocess.run(["codex", "--version"], check=True, capture_output=True, timeout=10)
        subprocess.run(["codex", "login", "status"], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        # Never print authentication output or credentials.
        raise RuntimeError("Codex is not ready. Run codex --version and codex login on the presenter laptop") from error
    return "Codex CLI and login are available (model connectivity is not tested)"


def check_sandbox():
    from .sandbox import execute
    with tempfile.TemporaryDirectory(prefix="evolve-preflight-") as temporary, socket.socket() as listener:
        folder = Path(temporary)
        sentinel = folder / "private.txt"
        sentinel.write_bytes(b"preflight sentinel")
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        source = folder / "probe.py"
        source.write_text("""import json, socket, statistics
result = {'mean': statistics.mean([1, 3])}
for mode, key in [('r', 'denied_read'), ('r+', 'denied_write')]:
    try:
        with open(%r, mode):
            pass
        result[key] = False
    except OSError:
        result[key] = True
try:
    with socket.create_connection(('127.0.0.1', %d), timeout=1):
        pass
    result['denied_network'] = False
except OSError:
    result['denied_network'] = True
print(json.dumps(result))
""" % (str(sentinel), listener.getsockname()[1]))
        result, name = execute(source, b"")
        if result != {"mean": 2, "denied_read": True, "denied_write": True, "denied_network": True}:
            raise RuntimeError("Sandbox did not deny private-file or host-network access; do not run generated code")
        if sentinel.read_bytes() != b"preflight sentinel":
            raise RuntimeError("Sandbox changed a trusted sentinel; do not run generated code")
    return name + ": scientific execution works; private-file and host-network probes denied"


def check_dependencies():
    try:
        version = importlib.metadata.version("jsonschema")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError("Python dependencies are missing. Run uv sync --frozen, then use uv run --frozen") from error
    if version != "4.26.0":
        raise RuntimeError("Use the locked jsonschema==4.26.0 environment: uv sync --frozen")
    return "Locked jsonschema==4.26.0 is installed"


def check_archive(path):
    from .archive import validate_archive
    return validate_archive(json.loads(path.read_text()))


def check_port(port):
    try:
        with socket.socket() as probe:
            # Match the presenter's immediate restart behavior after a connection closes.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            probe.listen()
    except OSError as error:
        raise RuntimeError(f"Cannot bind loopback port {port}. Stop the previous presenter with Ctrl+C or choose --port with another unused port") from error
    return "Loopback port is available"


def readiness(port, archive_path, *, archive_only=False):
    checks = []
    bundle = None

    def run(name, action, *, required=True):
        try:
            detail = action()
            checks.append(("PASS", name, str(detail)))
            return True
        except (OSError, ValueError, RuntimeError, ImportError) as error:
            checks.append(("FAIL" if required else "WARN", name, str(error)))
            return False

    run("Python", check_python)
    dependencies = run("Dependencies", check_dependencies)
    if dependencies:
        try:
            bundle = check_archive(archive_path)
            checks.append(("PASS", "Previous run", "Original IDs, source revisions and frozen calibration verified; no code executed"))
        except (OSError, ValueError, ImportError) as error:
            checks.append(("FAIL", "Previous run", str(error)))
    else:
        checks.append(("FAIL", "Previous run", "Cannot validate archive until dependencies are installed"))
    run("Port", lambda: check_port(port))
    sandbox = run("Offline sandbox", check_sandbox, required=not archive_only)
    if bundle is not None and sandbox:
        def replay():
            from .replay_bundle import replay_package
            replay_package(bundle)
            return "Both archived analyses re-executed and match their retained results"
        run("Archive replay", replay, required=not archive_only)
    else:
        checks.append(("WARN" if archive_only else "FAIL", "Archive replay", "Not executed; requires validated archive and working offline sandbox"))
    if not archive_only:
        run("Coding worker", check_worker)
    else:
        checks.append(("INFO", "Coding worker", "Archive-only mode: no worker called; fresh generation is disabled"))
    return checks, bundle


def check_python():
    if not (3, 11) <= sys.version_info[:2] < (3, 15) or platform.system() not in ("Darwin", "Linux"):
        raise RuntimeError("Use Python 3.11–3.14 on macOS or Linux")
    return platform.python_version() + " on " + platform.system()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run readiness checks without starting a server or generating code")
    parser.add_argument("--archive-only", action="store_true", help="Inspect the previous run without Codex; replay still requires the offline sandbox")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--store", type=Path, default=ROOT / "runs" / "b12")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    checks, bundle = readiness(args.port, ROOT / "public/b12/completed.json", archive_only=args.archive_only)
    for status, name, detail in checks:
        print(f"{status:4} {name}: {detail}", flush=True)
    if any(status == "FAIL" for status, _, _ in checks):
        print("Demo not ready. Resolve the failures above." +
              (" For read-only fallback, use --archive-only." if not args.archive_only else ""), flush=True)
        return 1
    if args.check:
        return 0
    from .lab import serve
    print("Previous completed run is read-only; recorded replay outcomes are not a new execution.", flush=True)
    if args.archive_only:
        print("Archive-only viewing: no fresh generation. Replay is unavailable if the sandbox check warned.", flush=True)
    else:
        print("Fresh generation requires the worker's model connection; no 8090 connection is needed.", flush=True)
    try:
        serve(args.port, args.store, archive=bundle, allow_generation=not args.archive_only)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Cannot start presenter: {error}. Check --store and --port; do not delete existing evidence.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
