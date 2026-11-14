"""Run the local UV–Vis simulator: python -m factory.uvvis_http --help."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re

from .context import read_json
from .uvvis_contract import InstrumentError
from .uvvis_service import VirtualUvVisService


class InstrumentHandler(BaseHTTPRequestHandler):
    def _json_body(self):
        if self.headers.get_content_type() != "application/json":
            raise InstrumentError("Content-Type", "application/json required", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError
            return json.loads(self.rfile.read(length))
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
        match = re.fullmatch(r"/v1/acquisitions/([a-f0-9]{32})(?:/(cancel|measurements))?", self.path)
        if match:
            job_id, action = match.groups()
            if self.command == "GET" and action is None:
                return 200, service.job(job_id)
            if self.command == "GET" and action == "measurements":
                return 200, service.measurements(job_id)
            if self.command == "POST" and action == "cancel":
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
