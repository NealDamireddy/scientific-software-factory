"""Run the local UV–Vis simulator: python -m factory.instruments.uvvis_http --help."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import time

from factory.context import read_json
from factory.instruments.uvvis_contract import InstrumentError, pin_sha256, validate, validate_pins
from factory.instruments.uvvis_service import VirtualUvVisService


def _check_job(service, job_id, pin):
    job = service.job(job_id)
    validate("job", job)
    validate_pins(pin, job)
    if job["job_id"] != job_id:
        raise InstrumentError("job_id", "does not match the requested acquisition", 409)


class InstrumentHandler(BaseHTTPRequestHandler):
    body_timeout_s = 2.0

    def _content_length(self):
        lengths = self.headers.get_all("Content-Length", [])
        if "Transfer-Encoding" in self.headers or len(lengths) > 1:
            raise InstrumentError("body", "supply a single Content-Length", 400)
        if not lengths:
            return 0
        value = lengths[0]
        if not re.fullmatch(r"[0-9]+", value) or len(value.lstrip("0")) > 5:
            raise InstrumentError("body", "invalid Content-Length", 400)
        length = int(value.lstrip("0") or "0")
        if length > 65536:
            raise InstrumentError("body", "maximum body size is 64 KiB", 400)
        return length

    def _json_body(self, length=None):
        if self.headers.get_content_type() != "application/json":
            raise InstrumentError("Content-Type", "application/json required", 415)
        if length is None:
            length = self._content_length()
        body = bytearray()
        deadline = time.monotonic() + self.body_timeout_s
        previous_timeout = self.connection.gettimeout()
        try:
            while len(body) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                # read1 performs at most one socket read, even if a client
                # keeps sending single bytes just inside the previous timeout.
                chunk = self.rfile.read1(length - len(body))
                if not chunk:
                    raise InstrumentError("body", "incomplete request body", 400)
                body.extend(chunk)
        except TimeoutError:
            raise InstrumentError("body", "request body deadline exceeded", 408) from None
        finally:
            self.connection.settimeout(previous_timeout)
        try:
            return json.loads(body)
        except (ValueError, RecursionError):
            raise InstrumentError("body", "supply a valid JSON body up to 64 KiB", 400) from None

    def _route(self):
        port = self.server.server_port
        host = self.headers.get("Host")
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}") or self.headers.get("Origin", f"http://{host}") != f"http://{host}":
            raise InstrumentError("Host", "local instrument requests only", 403)
        service = self.server.instrument
        if self.command == "GET" and self.path == "/v1/capabilities":
            return 200, service.capabilities
        if self.command == "POST" and self.path == "/v1/blanks":
            return 201, service.blank(self._json_body())
        if self.command == "POST" and self.path == "/v1/acquisitions":
            return 202, service.submit(self._json_body(), self.headers.get("Idempotency-Key"))
        match = re.fullmatch(r"/v1/acquisitions/([a-f0-9]{32})(?:/(cancel|measurements))?"
                             r"(?:\?pin_sha256=([a-f0-9]{64}))?", self.path)
        if match:
            job_id, action, expected_pin = match.groups()
            if expected_pin is not None and expected_pin != pin_sha256(service.pin):
                raise InstrumentError("pin_sha256", "does not match this instrument and profile", 409)
            if self.command == "GET" and action is None:
                return 200, service.job(job_id)
            if self.command == "GET" and action == "measurements":
                with service.lock:
                    if expected_pin is not None:
                        # An empty result has no record pins. Its historical
                        # job must belong to the live instance serving this GET.
                        _check_job(service, job_id, service.pin)
                    return 200, service.measurements(job_id)
            if self.command == "POST" and action == "cancel":
                # Legacy callers use a bodyless POST. Pinned clients repeat
                # their precondition on the request that performs the mutation.
                length = self._content_length()
                pin = self._json_body(length) if length else service.pin
                validate("pin", pin)
                with service.lock:
                    validate_pins(pin, service.capabilities)
                    _check_job(service, job_id, pin)
                    return 200, service.cancel(job_id)
        raise InstrumentError("path", "unknown instrument route", 404)

    def dispatch(self):
        try:
            status, result = self._route()
        except InstrumentError as error:
            status, result = error.status, {"field": error.field, "reason": error.reason}
        body = json.dumps(result, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET = dispatch


def make_server(service, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), InstrumentHandler)
    server.daemon_threads = False
    server.instrument = service
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path, help="Directory for simulator jobs and references")
    parser.add_argument("--samples", required=True, type=Path,
                        help="Private JSON object keyed by sample ID, with concentration_mg_l and optional rate_mg_l_s")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--duration", type=float, default=1, help="Seconds per replicate (0–60)")
    parser.add_argument("--noise", type=float, default=8, help="Detector noise SD in counts (0–100)")
    args = parser.parse_args()
    service = VirtualUvVisService(args.store, read_json(args.samples), noise_sd_counts=args.noise, duration_s=args.duration)
    try:
        with make_server(service, args.port) as server:
            print(f"http://127.0.0.1:{server.server_port}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()


if __name__ == "__main__":
    main()
