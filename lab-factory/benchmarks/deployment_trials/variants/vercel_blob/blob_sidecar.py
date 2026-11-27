"""Loopback Blob GET and conditional PUT for the SQLite snapshot and tabular originals."""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit


KEY = "labfactory/lab.sqlite3"
UPLOAD = re.compile(r"labfactory/uploads/([0-9a-f]{64})")
LIMIT = 8 * 1024 * 1024


def etag(data):
    return '"' + hashlib.sha256(data).hexdigest() + '"'


class BlobServer(ThreadingHTTPServer):
    def __init__(self, port, directory, token, events=None):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory = directory
        (directory / "uploads").mkdir(mode=0o700, exist_ok=True)
        self.authorization = ("Bearer " + token).encode("ascii")
        self.events = events
        self.lock = threading.Lock()
        self.log_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), BlobHandler)

    def object_path(self, key):
        if key == KEY:
            return self.directory / "lab.sqlite3"
        match = UPLOAD.fullmatch(key)
        return self.directory / "uploads" / match[1] if match else None

    @staticmethod
    def read_object(path):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    @staticmethod
    def replace_object(path, data):
        directory = path.parent
        fd, temporary = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def record(self, method, status, key_type, byte_count, start):
        if self.events:
            event = {"method": method, "status": status, "object_type": key_type, "object_bytes": byte_count,
                     "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
            with self.log_lock, self.events.open("a", encoding="utf-8") as output:
                output.write(json.dumps(event) + "\n")


class BlobHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, status, body=b"", *, tag=None, byte_count=0):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream" if tag else "application/json")
        if tag:
            self.send_header("ETag", tag)
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.server.record(self.command, status, self.key_type, byte_count, self.started)

    def authorized(self):
        self.started = time.perf_counter()
        self.key_type = None
        value = self.headers.get("Authorization", "").encode("latin-1")
        if secrets.compare_digest(value, self.server.authorization):
            return True
        self.close_connection = True
        self.reply(401)
        return False

    def do_GET(self):
        if not self.authorized():
            return
        url = urlsplit(self.path)
        path = self.server.object_path(url.path.removeprefix("/"))
        if path is None or parse_qs(url.query) != {"cache": ["0"]}:
            self.reply(404)
            return
        if self.headers.get("Accept-Encoding") != "identity":
            self.reply(400)
            return
        self.key_type = "snapshot" if path.name == "lab.sqlite3" else "original"
        with self.server.lock:
            current = self.server.read_object(path)
        if current is None:
            self.reply(404)
        else:
            self.reply(200, current, tag=etag(current), byte_count=len(current))

    def do_PUT(self):
        if not self.authorized():
            return
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        keys = query.get("pathname", [])
        path = self.server.object_path(keys[0]) if len(keys) == 1 else None
        if url.path != "/api/blob/" or query.keys() != {"pathname"} or path is None:
            self.close_connection = True
            self.reply(404)
            return
        expected = self.headers.get("x-if-match")
        self.key_type = "snapshot" if path.name == "lab.sqlite3" else "original"
        required = {"x-api-version": "13", "x-vercel-blob-access": "private",
                    "x-add-random-suffix": "0", "x-allow-overwrite": "1" if expected else "0",
                    "x-content-type": "application/octet-stream"}
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or any(self.headers.get(k) != v for k, v in required.items()):
            self.close_connection = True
            self.reply(400)
            return
        if int(length) > LIMIT:
            self.close_connection = True
            self.reply(413)
            return
        data = self.rfile.read(int(length))
        if len(data) != int(length):
            self.close_connection = True
            self.reply(400)
            return
        with self.server.lock:
            current = self.server.read_object(path)
            if expected and (current is None or etag(current) != expected):
                status, body = 412, b""
            elif not expected and current is not None:
                status, body = 400, b'{"error":{"code":"bad_request","message":"This blob already exists"}}'
            else:
                self.server.replace_object(path, data)
                status, body = 200, b"{}"
        self.reply(status, body, byte_count=len(data) if status == 200 else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--events", type=Path, help="Optional sanitized per-request JSONL log")
    args = parser.parse_args()
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:
        parser.error("set BLOB_READ_WRITE_TOKEN to a disposable trial credential")
    with BlobServer(args.port, args.directory, token, args.events) as server:
        print(json.dumps({"port": server.server_port}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
