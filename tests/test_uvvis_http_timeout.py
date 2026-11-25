"""Exercise request framing and destructive preconditions on the real loopback service."""
from contextlib import closing
from http.client import HTTPConnection, HTTPResponse
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from factory.instruments.uvvis_adapter import VirtualInstrumentAdapter
from factory.instruments.uvvis_contract import pin_sha256
from factory.instruments.uvvis_http import InstrumentHandler, make_server
from factory.instruments.uvvis_service import VirtualUvVisService
from tests.test_uvvis_api import SAMPLES, SETTINGS


class InstrumentHttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.store = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.instrument_id = f"http-boundary-{uuid4().hex}"
        self.service = VirtualUvVisService(self.store, SAMPLES, instrument_id=self.instrument_id, duration_s=60)
        self.server = make_server(self.service)
        pin = self.service.pin
        self.api = VirtualInstrumentAdapter(f"http://127.0.0.1:{self.server.server_port}",
                                            self.instrument_id, pin["profile_id"], pin["profile_sha256"])

        def serve():
            with closing(self.service), self.server:
                self.server.serve_forever(poll_interval=0.01)

        self.thread = threading.Thread(target=serve)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        blank = self.api.blank(SETTINGS)
        self.request = {**pin, "blank_id": blank["blank_id"], "sample_ids": ["vial-q17"], "settings": SETTINGS}

    def send_incomplete(self, *, missing):
        client = self.enterContext(socket.create_connection(self.server.server_address, timeout=3))
        # The body already contains a valid acquisition. Dispatching it before
        # all advertised bytes arrive would start a real instrument job.
        body = json.dumps(self.request).encode()
        headers = (f"POST /v1/acquisitions HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n"
                   f"Content-Length: {len(body) + missing}\r\nContent-Type: application/json\r\n"
                   "Idempotency-Key: partial-body\r\n\r\n").encode()
        client.sendall(headers + body)
        return client

    def assert_no_acquisition(self, service):
        self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        self.assertEqual(service.db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 0)

    def assert_error(self, client, status):
        with HTTPResponse(client) as response:
            response.begin()
            self.assertEqual(response.status, status)
            self.assertEqual(json.loads(response.read())["field"], "body")

    def test_held_open_request_releases_server_and_both_leases(self):
        entered = threading.Event()
        read_body = InstrumentHandler._json_body

        def observe(handler):
            entered.set()
            return read_body(handler)

        with patch.object(InstrumentHandler, "_json_body", observe):
            client = self.send_incomplete(missing=1)
            self.assertTrue(entered.wait(3), "request did not enter body reader")
            self.server.shutdown()
            self.thread.join(4)
            self.assertFalse(self.thread.is_alive(), "server_close is still waiting for the body reader")
        # Keep our side of the socket open throughout shutdown and lease reacquisition.
        with closing(VirtualUvVisService(self.store, SAMPLES, instrument_id=self.instrument_id)) as reopened:
            self.assert_no_acquisition(reopened)
            self.assert_error(client, 408)

    def test_trickle_cannot_extend_body_deadline(self):
        client = self.send_incomplete(missing=4096)
        stop = threading.Event()

        def trickle():
            while not stop.wait(0.05):
                try:
                    client.sendall(b" ")
                except OSError:
                    break

        writer = threading.Thread(target=trickle)
        writer.start()
        try:
            self.assert_error(client, 408)
            self.assert_no_acquisition(self.service)
        finally:
            stop.set()
            writer.join()

    def test_valid_json_prefix_followed_by_premature_eof_is_rejected(self):
        client = self.send_incomplete(missing=1)
        client.shutdown(socket.SHUT_WR)
        self.assert_error(client, 400)
        self.assert_no_acquisition(self.service)

    def request_json(self, method, path, body=None, **headers):
        with closing(HTTPConnection(self.api.host, self.api.port, timeout=2)) as conn:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())

    def test_pin_digest_checked_by_each_job_route(self):
        job_id = self.api.submit(SETTINGS, self.request["sample_ids"], self.request["blank_id"], "owner")["job_id"]
        path = f"/v1/acquisitions/{job_id}"
        digest = pin_sha256(self.api.pin)
        guarded = f"?pin_sha256={digest}"
        foreign_pin = {**self.api.pin, "instrument_id": "other-instance"}
        queries = [(f"?pin_sha256={pin_sha256(foreign_pin)}", 409), ("?pin_sha256=bad", 404),
                   (guarded + "&extra=1", 404)]
        for suffix, method in (("", "GET"), ("/measurements", "GET"), ("/cancel", "POST")):
            for query, expected_status in queries:
                with self.subTest(suffix=suffix, query=query):
                    status, _ = self.request_json(method, path + suffix + query)
                    self.assertEqual(status, expected_status)
        self.assertEqual(self.api.poll(job_id)["status"], "running")
        for suffix in ("", "/measurements"):
            with self.subTest(suffix=suffix):
                status, result = self.request_json("GET", path + suffix + guarded)
                self.assertEqual((status, result["job_id"]), (200, job_id))
                self.assertEqual(self.request_json("GET", path + suffix), (status, result))
        # A historical job in the store may predate the server's current pins.
        # An empty measurement envelope by itself cannot prove ownership.
        foreign_job = {**self.api.poll(job_id), **foreign_pin}
        with patch.object(self.service, "job", return_value=foreign_job):
            status, error = self.request_json("GET", path + "/measurements" + guarded)
        self.assertEqual((status, error["field"]), (409, "instrument_id"))
        status, job = self.request_json("POST", path + "/cancel" + guarded, json.dumps(self.api.pin),
                                        **{"Content-Type": "application/json"})
        self.assertEqual((status, job["status"]), (200, "cancelled"))

    def test_pins_checked_at_cancel_and_legacy_bodyless_cancel(self):
        job_id = self.api.submit(SETTINGS, self.request["sample_ids"], self.request["blank_id"], "owner")["job_id"]
        path = f"/v1/acquisitions/{job_id}/cancel"
        headers = {"Content-Type": "application/json"}
        for field, value in (("instrument_id", "other-instrument"), ("profile_id", "virtual-uvvis@2"),
                             ("profile_sha256", "a" * 64)):
            with self.subTest(field=field):
                self.assertEqual(self.api.poll(job_id)["status"], "running")
                # Send a different precondition after the successful preflight.
                status, error = self.request_json("POST", path, json.dumps({**self.api.pin, field: value}), **headers)
                self.assertEqual(self.api.poll(job_id)["status"], "running")
                self.assertEqual((status, error["field"]), (409, field))
        job = self.api.poll(job_id)
        with patch.object(self.service, "job", return_value={**job, "job_id": uuid4().hex}):
            status, error = self.request_json("POST", path, json.dumps(self.api.pin), **headers)
        self.assertEqual(self.api.poll(job_id)["status"], "running")
        self.assertEqual((status, error["field"]), (409, "job_id"))
        for body, framing, expected in (("{}", {}, 422), ("{", {}, 400),
                                        (None, {"Transfer-Encoding": "chunked"}, 400)):
            with self.subTest(body=body, framing=framing):
                status, _ = self.request_json("POST", path, body, **headers, **framing)
                self.assertEqual(self.api.poll(job_id)["status"], "running")
                self.assertEqual(status, expected)
        status, job = self.request_json("POST", path)
        self.assertEqual((status, job["status"]), (200, "cancelled"))
