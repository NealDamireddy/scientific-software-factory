"""Run two pinned Lab Factory APIs and a round-robin entrypoint in a private runtime."""

import argparse
import contextlib
import fcntl
import http.client
import io
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


HERE = Path(__file__).resolve().parent
LAB = HERE.parents[3]
PYTHON = LAB / '.venv/bin/python'
RUNNER = HERE.parents[1] / 'acceptance.py'
COMMIT = '62badef1d608d94903da475bfd2b689cb80f9c49'
SERVICES = ('a', 'b', 'proxy')
SOCKET = 'replicas.sock'   # Relative to runtime to fit macOS Unix socket path limits.


def clean_env():
    return {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}


def prepare(runtime, requested_port):
    config = runtime / 'replicas.json'
    if not config.exists():
        port = requested_port or 18460
        if not 1024 <= port <= 65533:
            raise ValueError('Choose a base port between 1024 and 65533')
        reserved = ('source', 'lab.sqlite3', 'lab.sqlite3-wal', 'lab.sqlite3-shm', 'replicas.sock')
        if any((runtime / name).exists() for name in reserved):
            raise ValueError('Supply a fresh private runtime or a previously configured replica trial')
        config.write_text(json.dumps({'port': port, 'commit': COMMIT}))
    stored = json.loads(config.read_text())
    if stored['commit'] != COMMIT or requested_port not in (None, stored['port']):
        raise ValueError('Runtime belongs to another commit or port')
    port = stored['port']
    if not (runtime / 'source').exists():
        archive = subprocess.check_output(['git', '-C', LAB.parent, 'archive', COMMIT, 'lab-factory'])
        with tempfile.TemporaryDirectory(dir=runtime) as temporary:
            destination = Path(temporary) / 'source'
            with tarfile.open(fileobj=io.BytesIO(archive)) as files:
                files.extractall(destination, filter='data')
            destination.rename(runtime / 'source')
    db_path = runtime / 'lab.sqlite3'
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        if db.execute('PRAGMA journal_mode=WAL').fetchone() != ('wal',):
            raise RuntimeError('Cannot enable SQLite WAL')
    source = runtime / 'source/lab-factory'
    env = {**clean_env(), 'PYTHONPATH': str(source / 'src')}
    credentials = runtime / 'credentials.json'
    if not credentials.exists():
        subprocess.run([PYTHON, RUNNER, 'credentials', '--credentials', credentials], cwd=source,
                       env=env, stdout=subprocess.DEVNULL, check=True)
    settings = subprocess.check_output([PYTHON, RUNNER, 'env', '--base-url', f'http://127.0.0.1:{port}',
                                       '--credentials', credentials, '--private'], cwd=source, env=env)
    return port, {**env, **json.loads(settings), 'LABFACTORY_LOCAL_DB': str(db_path)}


class Services:
    def __init__(self, runtime, port, environ):
        self.runtime = runtime
        self.env = environ
        self.ports = {'proxy': port, 'a': port + 1, 'b': port + 2}
        self.children = {}

    def snapshot(self):
        return {'base_url': f'http://127.0.0.1:{self.ports["proxy"]}',
                'database': str(self.runtime / 'lab.sqlite3'),
                'processes': {name: {'port': port, 'pid': p.pid if (p := self.children.get(name))
                                     and p.poll() is None else None} for name, port in self.ports.items()}}

    def start(self, name):
        if self.snapshot()['processes'][name]['pid'] is not None:
            return
        port = self.ports[name]
        if name == 'proxy':
            command = [PYTHON, HERE / 'proxy.py', '--port', str(port), '--replica-a', str(self.ports['a']),
                       '--replica-b', str(self.ports['b'])]
        else:
            command = [PYTHON, '-m', 'uvicorn', 'labfactory.hosted:application', '--host', '127.0.0.1',
                       '--port', str(port), '--no-access-log', '--no-proxy-headers']
        # Reserve ports for the initial check; uvicorn and proxy each bind independently.
        # Poll process exit and the HTTP endpoint before reporting a service as ready.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
        with (self.runtime / f'{name}.log').open('ab') as log:
            child = self.children[name] = subprocess.Popen(command, stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, cwd=self.runtime / 'source/lab-factory',
                env=clean_env() if name == 'proxy' else self.env)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and child.poll() is None:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
            try:
                conn.request('GET', '/api/session')
                response = conn.getresponse()
                # A standalone gateway is operational even while both API processes are offline.
                if response.status == 200 or (name == 'proxy' and response.status in (502, 503)):
                    return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                conn.close()
            time.sleep(0.05)
        self.stop(name)
        raise RuntimeError(f'Service {name} failed to start. Inspect {self.runtime / (name + ".log")}')

    def stop(self, name):
        child = self.children.pop(name, None)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def dispatch(self, action, target):
        names = SERVICES if target == 'all' else (target,)
        if action == 'start':
            started = []
            try:
                for name in names:
                    if self.snapshot()['processes'][name]['pid'] is None:
                        self.start(name)
                        started.append(name)
            except Exception:
                for name in reversed(started):
                    self.stop(name)
                raise
        elif action == 'stop':
            for name in reversed(names):
                self.stop(name)
        return self.snapshot()


def manage(runtime, port, foreground):
    # Keep Popen handles in one supervisor so stop can only signal our own children.
    with (runtime / 'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        port, env = prepare(runtime, port)
        services = Services(runtime, port, env)
        running = True

        def shutdown(*_):
            nonlocal running
            running = False

        class Control(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    action, target = json.loads(self.rfile.readline(1024))
                    if action not in ('status', 'start', 'stop') or target not in (*SERVICES, 'all'):
                        raise ValueError('Unknown lifecycle command')
                    result = services.dispatch(action, target)
                    if action == 'stop' and target == 'all':
                        shutdown()
                except Exception as exc:
                    result = {'error': str(exc)}
                self.wfile.write(json.dumps(result).encode() + b'\n')

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        Path(SOCKET).unlink(missing_ok=True)
        try:
            with socketserver.UnixStreamServer(SOCKET, Control) as server:
                server.timeout = 0.3
                if foreground:
                    print(json.dumps(services.dispatch('start', 'all')), flush=True)
                while running:
                    server.handle_request()
        finally:
            services.dispatch('stop', 'all')
            Path(SOCKET).unlink(missing_ok=True)


def request(action, target):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(65)
        conn.connect(SOCKET)
        conn.sendall(json.dumps([action, target]).encode() + b'\n')
        with conn.makefile('rb') as incoming:
            response = json.loads(incoming.readline())
    if 'error' in response:
        raise RuntimeError(response['error'])
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path, help='Private directory, kept across restarts')
    parser.add_argument('--port', type=int, help='Proxy port; APIs use port+1 and port+2 (default 18460)')
    parser.add_argument('action', choices=('start', 'stop', 'status', 'serve', '_manage'))
    parser.add_argument('service', nargs='?', default='all', choices=('all', *SERVICES))
    args = parser.parse_args()
    os.umask(0o077)
    runtime = args.runtime.resolve()
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    if runtime.stat().st_uid != os.getuid() or stat.S_IMODE(runtime.stat().st_mode) & 0o077:
        parser.error('Use a private runtime directory owned by you (mode 0700)')
    os.chdir(runtime)
    if args.action in ('serve', '_manage'):
        manage(runtime, args.port, foreground=args.action == 'serve')
        return
    # Serialize client commands, including a stop immediately followed by a fresh start.
    with (runtime / 'client.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = runtime / 'replicas.json'
        port = args.port or 18460
        if config.exists():
            port = json.loads(config.read_text())['port']
            if args.port not in (None, port):
                raise ValueError('Supplied port differs from this runtime')
        try:
            result = request(args.action, args.service)
        except (FileNotFoundError, ConnectionRefusedError):
            if args.action != 'start':
                result = Services(runtime, port, {}).snapshot()
            else:
                with (runtime / 'supervisor.log').open('ab') as log:
                    child = subprocess.Popen([PYTHON, Path(__file__).resolve(), '--runtime', runtime,
                        '--port', str(port), '_manage'], stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, start_new_session=True, env=clean_env())
                deadline = time.monotonic() + 20
                try:
                    while child.poll() is None and time.monotonic() < deadline:
                        try:
                            result = request('start', args.service)
                            break
                        except (FileNotFoundError, ConnectionRefusedError):
                            time.sleep(0.1)
                    else:
                        raise RuntimeError(f'Supervisor failed to start. Inspect {runtime / "supervisor.log"}')
                except BaseException:
                    if child.poll() is None:
                        child.terminate()
                        child.wait()
                    raise
        if args.action == 'stop' and args.service == 'all':
            # Wait for supervisor to release its lock and remove its socket before restart.
            with (runtime / 'supervisor.lock').open('a') as stopped:
                fcntl.flock(stopped, fcntl.LOCK_EX)
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
