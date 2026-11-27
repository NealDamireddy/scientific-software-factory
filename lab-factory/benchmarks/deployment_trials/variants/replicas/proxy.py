"""Single-process, loopback-only round-robin HTTP entrypoint for this trial."""

import argparse
import itertools
from contextlib import asynccontextmanager

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


HOP_HEADERS = {
    b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization",
    b"proxy-connection", b"te", b"trailer", b"transfer-encoding", b"upgrade",
}


def forwarded_headers(headers):
    excluded = HOP_HEADERS | {b"x-lab-replica"}
    for name, value in headers:
        if name.lower() == b"connection":
            excluded.update(token.strip().lower() for token in value.split(b","))
    return [(name.lower(), value) for name, value in headers if name.lower() not in excluded]


class RoundRobin:
    def __init__(self, port_a, port_b):
        self.upstreams = [
            (b"a", httpx.URL(f"http://127.0.0.1:{port_a}")),
            (b"b", httpx.URL(f"http://127.0.0.1:{port_b}")),
        ]
        self.first = itertools.cycle((0, 1))

    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        target = scope["raw_path"]
        if scope["query_string"]:
            target += b"?" + scope["query_string"]
        headers = forwarded_headers(scope["headers"])
        has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
        first = next(self.first)
        for position in (first, 1 - first):
            label, origin = self.upstreams[position]
            upstream = httpx.Request(
                scope["method"], origin.copy_with(raw_path=target), headers=headers,
                content=request.stream() if has_body else None,
            )
            try:
                response = await request.state.client.send(upstream, stream=True)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                # Only connection establishment failed. No request bytes went upstream.
                continue
            except httpx.TransportError:
                # The upstream may have accepted a write before the connection failed.
                result = JSONResponse({"error": "Replica response could not be confirmed."}, 502)
                await result(scope, receive, send)
                return
            try:
                headers_out = forwarded_headers(response.headers.raw)
                headers_out.append((b"x-lab-replica", label))
                await send({"type": "http.response.start", "status": response.status_code,
                            "headers": headers_out})
                async for chunk in response.aiter_raw():
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b""})
            finally:
                await response.aclose()
            return
        unavailable = JSONResponse({"error": "Both replicas are unreachable."}, 503)
        await unavailable(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("--port", "--replica-a", "--replica-b"):
        parser.add_argument(option, type=int, required=True)
    args = parser.parse_args()
    ports = (args.port, args.replica_a, args.replica_b)
    if len(set(ports)) != 3 or any(port < 1 or port > 65535 for port in ports):
        parser.error("Supply three distinct TCP ports between 1 and 65535.")

    @asynccontextmanager
    async def lifespan(app):
        # New upstream TCP connections make a stopped replica detectable before a write.
        async with httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=0),
            timeout=httpx.Timeout(60, connect=1), trust_env=False,
        ) as client:
            yield {"client": client}

    endpoint = RoundRobin(args.replica_a, args.replica_b)
    app = Starlette(routes=[Route("/{path:path}", endpoint)], lifespan=lifespan)
    uvicorn.run(app, host="127.0.0.1", port=args.port, ws="none", proxy_headers=False,
                access_log=False, server_header=False, date_header=False)


if __name__ == "__main__":
    main()
