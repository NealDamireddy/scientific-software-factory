"""Serve the combined Lab Factory portal on loopback with a local SQLite store."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory

import uvicorn
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from urllib.parse import urlsplit

from labfactory.hosted import _json_body, make_portal


PROJECT = Path(__file__).resolve().parents[1]
portal = make_portal(PROJECT / "public")
# The header sources in this deployment are exact paths or parenthesized regular expressions.
HEADER_RULES = [
    (re.compile(rule["source"] if "(" in rule["source"] else re.escape(rule["source"])), rule["headers"])
    for rule in json.loads((PROJECT / "vercel.json").read_text())["headers"]
]


async def local_application(scope, receive, send):
    async def send_with_headers(message):
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            for path, fields in HEADER_RULES:
                if path.fullmatch(scope["path"]):
                    for field in fields:
                        headers[field["key"]] = field["value"]
        await send(message)

    if scope["type"] == "http" and scope["path"] == "/api/experiment-review":
        request = Request(scope, receive)
        origin = request.headers.get("origin", "")
        loopback = {"127.0.0.1", "localhost", "::1"}
        try:
            if (request.method != "POST" or os.environ.get("LAB_LOCAL_EXPERIMENT_WORKER") != "1"
                    or request.url.hostname not in loopback or not request.client or request.client.host not in loopback
                    or urlsplit(origin).hostname not in loopback or origin != f"{request.url.scheme}://{request.headers.get('host')}"
                    or request.headers.get("x-forwarded-host", request.headers.get("host")) != request.headers.get("host")
                    or any(ip.strip() not in loopback for ip in request.headers.get("x-forwarded-for", request.client.host).split(","))):
                raise HTTPException(403, "Local experiment review requires an enabled loopback workspace.")
            from lab_codex_worker.experiment_review import DeliveryConflict, review_delivery
            payload = await _json_body(request, 160 * 1024)
            state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
            try:
                body = await run_in_threadpool(review_delivery, payload, state / "lab-factory" / "skill-deliveries")
            except DeliveryConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "Check the experiment briefing and skill versions.") from exc
            except (RuntimeError, OSError) as exc:
                raise HTTPException(503, "Local coding worker unavailable. Check its sign-in and retry.") from exc
            response = JSONResponse(body)
        except HTTPException as exc:
            response = JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        response.headers["Cache-Control"] = "private, no-store"
        await response(scope, receive, send_with_headers)
    else:
        await portal(scope, receive, send_with_headers)


async def serve_with_worker(database, port):
    from labfactory.hosted_auth import token_digest
    from labfactory.store import Store
    from labfactory.tabular_worker import once

    identity, token = "Local drift author", secrets.token_urlsafe(32)
    configured = json.loads(os.environ.get("LABFACTORY_AGENTS", "{}"))
    os.environ["LABFACTORY_AGENTS"] = json.dumps({**configured, identity: token_digest(token)})
    server = uvicorn.Server(uvicorn.Config(local_application, host="127.0.0.1", port=port, access_log=False))

    async def work():
        with Store(database) as store:
            while not server.should_exit:
                if server.started:
                    jobs = store.connection.execute(
                        "SELECT id FROM drift_requests WHERE id LIKE 'PLOT-%' AND (status='open' OR (status='in_progress' AND worker=?)) "
                        "ORDER BY rowid", (identity,)).fetchall()
                    for job in jobs:
                        if server.should_exit:
                            break
                        try:
                            await once(f"http://127.0.0.1:{port}/mcp", token, identity, job["id"])
                        except Exception as exc:
                            print(f"Local drift author: {type(exc).__name__}: {exc}", flush=True)
                await asyncio.sleep(3)
    task = asyncio.create_task(work())
    try:
        await server.serve()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def serve(database, port, drift_worker=False):
    database.parent.mkdir(parents=True, exist_ok=True)
    for key in ("VERCEL", "VERCEL_ENV"):
        os.environ.pop(key, None)
    os.environ["LABFACTORY_LOCAL_DB"] = str(database)
    os.environ["LABFACTORY_PUBLIC_REVIEW"] = "1"
    os.environ.setdefault("LABFACTORY_AGENTS", "{}")
    print(f"Lab Factory researcher workspace: http://127.0.0.1:{port}/\n"
          f"Local work orders: {database}", flush=True)
    if drift_worker:
        asyncio.run(serve_with_worker(database, port))
    else:
        uvicorn.run(local_application, host="127.0.0.1", port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--drift-worker", action="store_true", help="Process queued stage plots with the signed-in local author.")
    parser.add_argument("--database", type=Path, default=os.environ.get("LABFACTORY_LOCAL_DB"),
                        help="Use an existing Lab Factory SQLite database.")
    parser.add_argument("--temporary", action="store_true", help="Discard this local session's orders on exit.")
    args = parser.parse_args()
    if not all((PROJECT / f"public/{site}/index.html").is_file() for site in ("evolve", "research")):
        parser.error("Run npm run build:lab from the repository root to build the researcher workspace and EVOLVE demos.")
    if args.temporary:
        with TemporaryDirectory(prefix="lab-portal-") as scratch:
            serve(Path(scratch) / "portal.sqlite3", args.port, args.drift_worker)
    else:
        serve(args.database or PROJECT.parent / "runs/lab-factory/portal.sqlite3", args.port, args.drift_worker)


if __name__ == "__main__":
    main()
