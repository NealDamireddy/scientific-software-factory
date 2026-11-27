"""Forward HTTPS Hrana requests to a separate loopback HTTP SQL server."""

import argparse
from collections import Counter
import hmac
from http import HTTPStatus
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import ssl
from threading import Event, Lock


POST_PATHS = {"/v3/cursor", "/v3/pipeline"}
LOOPBACK = "127.0.0.1"


class ProxyServer(ThreadingHTTPServer):
    # Wait for in-flight forwarding before the final status counters are saved.
    daemon_threads = False


class Counts:
    def __init__(self):
        self.lock = Lock()
        self.paths = Counter()
        self.statuses = Counter()
        self.upstream_failures = 0

    def record(self, path, status, upstream_failed=False):
        with self.lock:
            self.paths[path] += 1
            self.statuses[status] += 1
            self.upstream_failures += upstream_failed

    def write(self, target, snapshot_number):
        with self.lock:
            total = sum(self.statuses.values())
            successful = sum(n for status, n in self.statuses.items() if 200 <= status < 300)
            data = {
                "snapshot_number": snapshot_number,
                "requests": total,
                "successful_requests": successful,
                "failed_requests": total - successful,
                "unexpected_paths": self.paths["other"],
                "upstream_transport_failures": self.upstream_failures,
                "by_path": dict(self.paths),
                "by_status": dict(self.statuses),
            }
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(target)


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True
    timeout = 8
    upstream = None

    def log_message(self, *_):
        pass

    def finish(self):
        try:
            super().finish()
        finally:
            if self.upstream:
                self.upstream.close()

    def reply(self, status, data=b"", content_type="application/json", *, upstream_failed=False):
        label = self.path if self.path in POST_PATHS or self.path == "/v3" else "other"
        self.server.counts.record(label, status, upstream_failed)
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", content_type)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def forward(self):
        token = self.headers.get("Authorization", "").encode("latin-1")
        if not hmac.compare_digest(token, self.server.authorization):
            self.close_connection = True
            return self.reply(HTTPStatus.UNAUTHORIZED)
        allowed = POST_PATHS if self.command == "POST" else {"/v3"}
        if self.path not in allowed:
            self.close_connection = True
            return self.reply(HTTPStatus.NOT_FOUND)

        length = self.headers.get("Content-Length", "0")
        if not length.isascii() or not length.isdecimal() or len(length) > 10 or "Transfer-Encoding" in self.headers:
            self.close_connection = True
            return self.reply(HTTPStatus.BAD_REQUEST)
        length = int(length)
        if length > 16 * 1024 * 1024:
            self.close_connection = True
            return self.reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = self.rfile.read(length)
        if len(body) != length:
            self.close_connection = True
            return self.reply(HTTPStatus.BAD_REQUEST)

        if self.upstream is None:
            self.upstream = HTTPConnection(LOOPBACK, self.server.upstream_port, timeout=8)
        try:
            self.upstream.request(self.command, self.path, body=body, headers={
                "Authorization": token.decode("latin-1"),
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Accept-Encoding": "identity",
            })
            response = self.upstream.getresponse()
            payload = response.read()
            content_type = response.getheader("Content-Type", "application/json")
        except (OSError, HTTPException):
            self.upstream.close()
            self.upstream = None
            return self.reply(HTTPStatus.SERVICE_UNAVAILABLE, upstream_failed=True)
        self.reply(response.status, payload, content_type)

    do_GET = forward
    do_POST = forward


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--stats", type=Path, required=True)
    args = parser.parse_args()
    token = os.getenv("TURSO_AUTH_TOKEN")
    if not token:
        parser.error("set TURSO_AUTH_TOKEN to the disposable backend bearer token")

    stopped = Event()
    requested_snapshot = 0
    snapshot_number = 0

    def request_snapshot(*_):
        nonlocal requested_snapshot
        requested_snapshot += 1

    signal.signal(signal.SIGUSR1, request_snapshot)
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    counts = Counts()
    with ProxyServer((LOOPBACK, args.port), Proxy) as server:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        server.authorization = ("Bearer " + token).encode("ascii")
        server.counts = counts
        server.upstream_port = args.upstream_port
        server.timeout = 0.1
        while not stopped.is_set():
            server.handle_request()
            while snapshot_number < requested_snapshot:
                snapshot_number += 1
                counts.write(args.stats, snapshot_number)
    counts.write(args.stats, requested_snapshot)


if __name__ == "__main__":
    main()
