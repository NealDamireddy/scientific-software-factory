"""Shared operator API, browser portal, and remote agent entry point."""

from dataclasses import asdict
import json
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .artifacts import Procedure, parse_artifact, render_procedure, render_run_plan
from .context import ContextError, experiment_from_dict, lab_from_dict, unique_fields
from .hosted_auth import Access, SESSION_COOKIE, SESSION_SECONDS
from .hosted_mcp import make_mcp_app
from .hosted_storage import HostedStorageError, run_store
from .store import NotFound
from .workorders import WorkOrderError, WorkOrders

PROJECT = Path(__file__).resolve().parents[2]
BODY_LIMIT = 1024 * 1024
HISTORY_PAGE = 30
STREAM_CHUNK = 64 * 1024


def _access() -> Access:
    try:
        return Access.from_env()
    except (KeyError, ValueError):
        raise HTTPException(503, "Sign-in is unavailable. Check the deployment configuration.") from None


def _response(data, status=200):
    headers = {"Cache-Control": "private, no-store"}
    response = JSONResponse(data, status_code=status, headers=headers)
    if len(response.body) <= BODY_LIMIT:
        return response

    # Large individual records and older API clients can still produce >4.5 MB.
    # Vercel supports streamed Python responses without a fixed Content-Length.
    async def chunks():
        body = memoryview(response.body)
        for start in range(0, len(body), STREAM_CHUNK):
            yield body[start:start + STREAM_CHUNK]
    return StreamingResponse(chunks(), status_code=status, media_type="application/json", headers=headers)


async def _json_body(request: Request) -> dict:
    scheme = "https" if os.getenv("VERCEL") else request.url.scheme
    if request.headers.get("origin") != f"{scheme}://{request.headers.get('host')}":
        raise HTTPException(403, "Send this request from the lab portal.")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Send application/json.")
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > BODY_LIMIT:
            raise HTTPException(413, "The JSON record exceeds 1 MiB.")
        body.extend(part)
    try:
        data = json.loads(body, object_pairs_hook=unique_fields)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, f"Invalid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Expected a JSON object.")
    return data


def _reviewer(request: Request) -> str:
    who = _access().reviewer(request.cookies.get(SESSION_COOKIE))
    if not who:
        raise HTTPException(401, "Sign in to the lab.")
    return who


def _session_data(access, name):
    data = {"reviewer": name}
    if name:
        data["agent_names"] = sorted(access.agents)
    return data


async def session(request):
    access = _access()
    return _response(_session_data(access, access.reviewer(request.cookies.get(SESSION_COOKIE))))


async def login(request):
    data = await _json_body(request)
    access = _access()
    name = data.get("name")
    if not await run_in_threadpool(access.verify_password, name, data.get("password")):
        raise HTTPException(401, "Incorrect reviewer name or password.")
    res = _response(_session_data(access, name))
    res.set_cookie(SESSION_COOKIE, access.session(name), max_age=SESSION_SECONDS,
                   secure=True, httponly=True, samesite="strict", path="/")
    return res


async def logout(request):
    await _json_body(request)
    res = _response({"reviewer": None})
    res.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
    return res


def _history_page(store, id, before=None):
    rows = list(store.connection.execute(
        """SELECT rowid AS cursor, event, actor, at, submission, note FROM events
           WHERE work_order_id=? AND rowid<=? ORDER BY rowid DESC LIMIT ?""",
        (id, before - 1 if before is not None else 2**63 - 1, HISTORY_PAGE + 1),
    ))
    visible = rows[:HISTORY_PAGE]
    next_cursor = visible[-1]["cursor"] if len(rows) > HISTORY_PAGE else None
    history = []
    for row in reversed(visible):
        event = dict(row)
        event.pop("cursor")
        history.append(event)
    return history, next_cursor


def _details(store, id, submission=None, before_event=None):
    orders = WorkOrders(store)
    page = {}
    with store.read_transaction():
        order = orders.get(id)
        if before_event is not None:
            submissions = []
            history, page["before_event"] = _history_page(store, id, before_event)
        elif submission is not None:
            sub = orders.submission(id, None if submission == "latest" else submission)
            submissions = [sub] if sub else []
            history, page["before_event"] = _history_page(store, id) if submission == "latest" else ([], None)
            page["older_submission"] = sub.number - 1 if sub and sub.number > 1 else None
        else:
            submissions = orders.submissions(id)
            history = orders.history(id)
    values = []
    for sub in submissions:
        artifact = parse_artifact(order.kind, sub.artifact)
        rendered = render_procedure(artifact) if isinstance(artifact, Procedure) else render_run_plan(artifact)
        values.append({**asdict(sub), "rendered": rendered})
    return {"order": asdict(order), "submissions": values, "history": history, **page}


def _positive_integer(value):
    try:
        parsed = int(value)
        if 0 < parsed < 2**63:
            return parsed
    except ValueError:
        pass
    raise HTTPException(400, "Expected a positive integer for the page cursor.")


async def order_detail(request):
    _reviewer(request)
    id = request.path_params["id"]
    submission = request.query_params.get("submission")
    before_event = request.query_params.get("before_event")
    if submission is not None and before_event is not None:
        raise HTTPException(400, "Request submissions or earlier history separately.")
    if submission is not None and submission != "latest":
        submission = _positive_integer(submission)
    if before_event is not None:
        before_event = _positive_integer(before_event)
    return _response(await run_in_threadpool(run_store, lambda store: _details(store, id, submission, before_event)))


async def order_list(request):
    reviewer = _reviewer(request)
    if request.method == "GET":
        orders = await run_in_threadpool(run_store, lambda store: [asdict(o) for o in WorkOrders(store).list()])
        return _response({"orders": orders})
    data = await _json_body(request)
    if not isinstance(data.get("experiment_id"), str):
        raise HTTPException(400, "Provide an experiment ID.")
    def create(store):
        return WorkOrders(store).create(data["experiment_id"], data.get("kind"), data.get("objective"), actor=reviewer)
    order = await run_in_threadpool(run_store, create, write=True)
    return _response({"id": order.id}, 201)


async def context_put(request):
    _reviewer(request)
    data = await _json_body(request)
    kind = request.path_params["kind"]
    if kind == "lab":
        record = lab_from_dict(data)
        def save(store):
            return store.put_lab(record)
    elif kind == "experiment":
        record = experiment_from_dict(data)
        def save(store):
            return store.put_experiment(record)
    else:
        raise HTTPException(404, "Unknown context kind.")
    revision = await run_in_threadpool(run_store, save, write=True)
    return _response({"id": record.id, "revision": revision.number, "digest": revision.digest})


async def example(request):
    reviewer = _reviewer(request)
    await _json_body(request)
    lab = lab_from_dict(json.loads((PROJECT / "examples/uvvis-lab.json").read_text()))
    exp = experiment_from_dict(json.loads((PROJECT / "examples/b12-experiment.json").read_text()))

    def create(store):
        # Seed absent records only. Preserve any revisions saved by this lab.
        try:
            store.get_lab(lab.id)
        except NotFound:
            store.put_lab(lab)
        try:
            store.get_experiment(exp.id)
        except NotFound:
            store.put_experiment(exp)
        return WorkOrders(store).create(exp.id, "run_plan", "Read the reference solution at 550 nm", actor=reviewer)
    order = await run_in_threadpool(run_store, create, write=True)
    return _response({"id": order.id}, 201)


async def decide(request):
    person = _reviewer(request)
    data = await _json_body(request)
    if data.pop("expected_reviewer", person) != person:
        raise HTTPException(409, "Reviewer changed in another tab. Reload the page and review the submission again.")
    id = request.path_params["id"]
    action = request.path_params["action"]
    number = data.get("submission")
    if type(number) is not int or number < 1:
        raise HTTPException(400, "Provide a positive submission number.")
    if action == "approve" and set(data) == {"submission"}:
        def review(store):
            return WorkOrders(store).approve(id, person, number)
    elif action == "reject" and set(data) == {"submission", "reason"}:
        def review(store):
            return WorkOrders(store).reject(id, person, number, data["reason"])
    else:
        raise HTTPException(400, "Invalid review decision or fields.")
    order = await run_in_threadpool(run_store, review, write=True)
    return _response({"id": order.id, "status": order.status})


async def domain_error(request, exc):
    if isinstance(exc, HTTPException):
        return _response({"error": exc.detail}, exc.status_code)
    if isinstance(exc, HostedStorageError):
        return _response({"error": "Lab storage is unavailable. Refresh the order before retrying."}, 503)
    status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, WorkOrderError) else 400
    return _response({"error": str(exc)}, status)


portal = Starlette(routes=[
    Route("/api/session", session), Route("/api/login", login, methods=["POST"]),
    Route("/api/logout", logout, methods=["POST"]), Route("/api/orders", order_list, methods=["GET", "POST"]),
    Route("/api/orders/{id}", order_detail), Route("/api/orders/{id}/{action}", decide, methods=["POST"]),
    Route("/api/context/{kind}", context_put, methods=["POST"]), Route("/api/example", example, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=PROJECT / "public", html=True, check_dir=False)),
], exception_handlers={cls: domain_error for cls in (HTTPException, ContextError, NotFound, WorkOrderError, HostedStorageError)})

# Vercel supplies the original request path even when routed to api/index.py.
mcp = make_mcp_app(run_store, lambda headers: _access().authenticate_agent(headers))


async def application(scope, receive, send):
    if scope["type"] == "http" and scope["path"] in ("/mcp", "/mcp/"):
        await mcp(scope, receive, send)
    else:
        await portal(scope, receive, send)
