"""Run the pinned Lab Factory ASGI app under a detached POSIX process supervisor."""

import argparse
from contextlib import closing
import fcntl
from http.client import HTTPConnection, HTTPException
import io
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

PIN = "62badef1d608d94903da475bfd2b689cb80f9c49"
SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[5]
AUTH = ("LABFACTORY_AGENTS", "LABFACTORY_REVIEWERS", "LABFACTORY_SESSION_KEY",
        "LABFACTORY_PUBLIC_REVIEW", "LABFACTORY_PUBLIC_ORIGIN")
CONTROL = "control.sock"
CONFIG = Path("config.json")
BASE_ENV = {"PATH": os.defpath, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def read_env_file(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("--env-file must be a regular file owned by the invoking user with mode 0600.")
        values = json.load(stream)
    if (not isinstance(values, dict) or set(values) - set(AUTH)
            or not all(isinstance(value, str) and "\x00" not in value for value in values.values())):
        raise ValueError("--env-file must contain a JSON object of supported Lab Factory auth settings.")
    return values


def configure(port, env_file):
    if CONFIG.exists():
        if env_file is not None:
            raise ValueError("--env-file applies only to the first start of a runtime.")
        config = json.loads(CONFIG.read_text())
        if config["commit"] != PIN or (port is not None and port != config["port"]):
            raise ValueError("The runtime belongs to a different release or port.")
        return config
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Supply --port 1..65535 when creating a runtime.")
    auth = read_env_file(env_file) if env_file is not None else {key: os.environ[key] for key in AUTH if key in os.environ}
    if "LABFACTORY_AGENTS" not in auth:
        raise ValueError("Provide the synthetic acceptance runner environment on first start.")
    if auth.get("LABFACTORY_PUBLIC_REVIEW") != "1" and not all(key in auth for key in AUTH[:3]):
        raise ValueError("Named-reviewer mode requires all three synthetic auth variables.")
    if auth.get("LABFACTORY_PUBLIC_REVIEW", "0") not in {"0", "1"}:
        raise ValueError("The public review flag must be 0 or 1.")
    origin = f"http://127.0.0.1:{port}"
    if auth.get("LABFACTORY_PUBLIC_ORIGIN", origin) != origin:
        raise ValueError("The supplied public origin must equal the service loopback URL.")

    if not Path("package").exists():
        archive = subprocess.check_output(["git", "archive", PIN, "lab-factory"], cwd=REPO)
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            staged = Path(tmp) / "package"
            with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                bundle.extractall(staged, filter="data")
            staged.rename("package")
    source = Path("package/lab-factory/src").resolve()
    checked = subprocess.run([sys.executable, "-c", "from labfactory.hosted_auth import Access; Access.from_env()"],
                             cwd=source, env={**BASE_ENV, **auth, "PYTHONPATH": str(source)},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if checked.returncode:
        raise ValueError("The pinned backend's authentication configuration check failed.")
    Path("volume").mkdir(mode=0o700, exist_ok=True)
    config = {"port": port, "commit": PIN, "auth": auth}
    with tempfile.NamedTemporaryFile(mode="w", dir=".", delete=False) as out:
        json.dump(config, out)
    os.replace(out.name, CONFIG)
    return config


def control(command):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        try:
            client.connect(CONTROL)
        except (FileNotFoundError, ConnectionRefusedError):
            return None
        client.sendall(command.encode("ascii"))
        return json.loads(client.makefile("rb").readline())


def ready(port):
    try:
        with closing(HTTPConnection("127.0.0.1", port, timeout=0.4)) as client:
            client.request("GET", "/api/session")
            response = client.getresponse()
            return response.status == 200 and "reviewer" in json.loads(response.read())
    except (OSError, ValueError, HTTPException):
        return False


def snapshot(port):
    status = control("status")
    if status is None:
        return dict(port=port, server_pid=None, supervisor_pid=None, generation=0, ready=False)
    status["ready"] = bool(status["server_pid"]) and ready(port)
    return status


def until(predicate, description, process=None):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        if process is not None and process.poll() is not None:
            raise RuntimeError("Supervisor exited during startup. See runtime/service.log.")
        time.sleep(0.05)
    raise RuntimeError(f"Timed out waiting for {description}. See runtime/service.log.")


def stopped():
    with open("supervisor.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def supervise(config):
    stop = False

    def request_stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    package = Path("package/lab-factory").resolve()
    env = {**BASE_ENV, **config["auth"], "LABFACTORY_LOCAL_DB": str(Path("volume/lab.sqlite3").resolve()),
           "PYTHONPATH": str(package / "src")}
    child = None
    generation = 0
    last_exit = None
    # Keep exclusive ownership of the port across child exits. Only our Popen
    # handle can receive a signal, never a PID read from a stale runtime file.
    with socket.socket(socket.AF_INET) as http, socket.socket(socket.AF_UNIX) as ctl:
        http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.bind(("127.0.0.1", config["port"]))
        fd = http.fileno()
        argv = [sys.executable, "-m", "uvicorn", "api.index:app", "--fd", str(fd), "--no-access-log"]
        Path(CONTROL).unlink(missing_ok=True)
        ctl.bind(CONTROL)
        ctl.listen(8)
        ctl.settimeout(0.1)
        try:
            while not stop:
                if child is None or child.poll() is not None:
                    if child is not None:
                        last_exit = child.returncode
                        time.sleep(0.25)
                    child = subprocess.Popen(argv, cwd=package, env=env, pass_fds=(fd,))
                    generation += 1
                try:
                    peer, _ = ctl.accept()
                except TimeoutError:
                    continue
                with peer:
                    peer.settimeout(2)
                    try:
                        command = peer.recv(32)
                        if command == b"crash":
                            child.kill()
                        elif command == b"stop":
                            stop = True
                        status = dict(port=config["port"], supervisor_pid=os.getpid(), server_pid=child.pid,
                                      generation=generation, last_exit=last_exit)
                        peer.sendall(json.dumps(status).encode() + b"\n")
                    except (TimeoutError, BrokenPipeError, ConnectionResetError):
                        pass
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            Path(CONTROL).unlink(missing_ok=True)


def run(command, runtime, port, env_file=None):
    os.umask(0o077)
    if env_file is not None:
        if command != "start":
            raise ValueError("--env-file is available only for the first start.")
        env_file = env_file.absolute()
    if command == "start":
        runtime.mkdir(mode=0o700, exist_ok=True, parents=True)
    if runtime.is_symlink() or runtime.stat().st_uid != os.getuid() or runtime.stat().st_mode & 0o077:
        raise ValueError("--runtime must be a private directory owned by the invoking user (0700).")
    os.chdir(runtime)
    if command == "_supervise":
        with open("supervisor.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            supervise(json.loads(CONFIG.read_text()))
        return

    with open("cli.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = configure(port, env_file) if command == "start" else json.loads(CONFIG.read_text())
        port = config["port"]
        process = None
        previous = None
        if command == "start" and control("status") is None:
            with open("service.log", "ab", buffering=0) as log:
                process = subprocess.Popen([sys.executable, str(SCRIPT), "_supervise", "--runtime", str(runtime)],
                                           cwd=runtime, env=BASE_ENV, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, start_new_session=True)
        elif command == "crash":
            previous = control("crash")
            if previous is None:
                raise ValueError("The service is stopped.")
        elif command == "stop":
            control("stop")
            until(stopped, "supervisor shutdown")
        if command in ("start", "crash"):
            def has_serving_child():
                state = snapshot(port)
                replaced = previous is None or state["generation"] > previous["generation"]
                return state if state["ready"] and replaced else None
            try:
                return until(has_serving_child, "an HTTP-ready ASGI child", process)
            except Exception:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=12)
                raise
        return snapshot(port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "crash", "stop", "_supervise"))
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--port", type=int, help="fixed IPv4 loopback port for the first start")
    parser.add_argument("--env-file", type=Path, help="mode-0600 JSON output from acceptance.py env for the first start")
    args = parser.parse_args()
    try:
        status = run(args.command, args.runtime.absolute(), args.port, args.env_file)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\n")
    if status is not None:
        print(json.dumps(status, sort_keys=True))


if __name__ == "__main__":
    main()
