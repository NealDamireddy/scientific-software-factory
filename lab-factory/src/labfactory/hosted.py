"""ASGI entry point for the reviewer API and authenticated remote agents."""

from dataclasses import asdict
import json
import os
from pathlib import Path
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import b12_service, experiment_catalog, honey_service, reference_orders, references, tabular_service
from .artifacts import render_artifact
from .context import ContextError, experiment_from_dict, lab_from_dict, unique_fields
from .hosted_auth import Access, PUBLIC_REVIEWER, SESSION_COOKIE, SESSION_SECONDS
from .hosted_mcp import make_mcp_app
from .hosted_storage import HostedStorageError, run_store
from .store import NotFound
from .workorders import WorkOrderError, WorkOrders

EXAMPLES = Path(__file__).with_name("examples")
if not EXAMPLES.is_dir():
    # The wheel includes these two source-controlled examples inside the package.
    EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
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
        raise HTTPException(403, "Supply the same origin as the reviewer API.")
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
    if access.public_review:
        data["access_mode"] = "public"
    if name:
        data["agent_names"] = sorted(access.agents)
    return data


async def session(request):
    access = _access()
    return _response(_session_data(access, access.reviewer(request.cookies.get(SESSION_COOKIE))))


async def login(request):
    data = await _json_body(request)
    access = _access()
    if access.public_review:
        return _response(_session_data(access, PUBLIC_REVIEWER))
    name = data.get("name")
    if not await run_in_threadpool(access.verify_password, name, data.get("password")):
        raise HTTPException(401, "Incorrect reviewer name or password.")
    res = _response(_session_data(access, name))
    res.set_cookie(SESSION_COOKIE, access.session(name), max_age=SESSION_SECONDS,
                   secure=True, httponly=True, samesite="strict", path="/")
    return res


async def logout(request):
    await _json_body(request)
    if _access().public_review:
        res = _response({"error": "Public reviewer access is always active."}, 409)
    else:
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
        brief = store.reference_brief(id)
        reports = {}
        if tabular_service.is_order(order) and before_event is None:
            page["analysis"] = tabular_service.reviewer_context(store, order)
            page["runs"] = tabular_service.list_runs(store.connection, id)
            reports = {r["submission"]: json.loads(r["report"]) for r in store.connection.execute(
                "SELECT submission,report FROM tabular_reports WHERE work_order_id=?", (id,))}
        if honey_service.is_honey_order(order) and before_event is None and submission in (None, "latest"):
            page["runs"] = honey_service.list_runs(store.connection, id)
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
        rendered = render_artifact(order.kind, sub.artifact, experiment_id=order.experiment_id)
        value = {**asdict(sub), "rendered": rendered}
        if tabular_service.is_order(order):
            value["control"] = reports.get(sub.number)
        values.append(value)
    if brief is not None:
        page["reference_brief"] = brief
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
    pins = ("expected_experiment_revision", "expected_lab_revision")
    check_revisions = any(key in data for key in pins)
    if check_revisions and not all(type(data.get(key)) is int and data[key] > 0 for key in pins):
        raise HTTPException(400, "Supply both expected revisions as positive integers.")

    def create(store):
        with store.transaction():
            order = WorkOrders(store).create(
                data["experiment_id"], data.get("kind"), data.get("objective"), actor=reviewer,
            )
            if check_revisions and (order.experiment_revision, order.lab_revision) != (data[pins[0]], data[pins[1]]):
                raise WorkOrderError("The experiment or lab has changed. Refresh the experiment before creating an order.")
            return order

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


async def experiment_list(request):
    _reviewer(request)
    return _response(await run_in_threadpool(run_store, experiment_catalog.list_experiments))


async def experiment_detail(request):
    _reviewer(request)
    experiment_id = request.path_params["id"]
    detail = await run_in_threadpool(run_store, lambda store: experiment_catalog.experiment_detail(store, experiment_id))
    return _response(detail)


async def order_context(request):
    _reviewer(request)
    order_id = request.path_params["id"]
    context = await run_in_threadpool(run_store, lambda store: experiment_catalog.order_context(store, order_id))
    return _response(context)


async def example(request):
    reviewer = _reviewer(request)
    await _json_body(request)
    lab = lab_from_dict(json.loads((EXAMPLES / "uvvis-lab.json").read_text(encoding="utf-8")))
    exp = experiment_from_dict(json.loads((EXAMPLES / "b12-experiment.json").read_text(encoding="utf-8")))

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


async def b12_catalog(request):
    _reviewer(request)
    return _response(await run_in_threadpool(run_store, b12_service.catalog))


async def analysis_catalog(request):
    _reviewer(request)
    return _response(await run_in_threadpool(run_store, tabular_service.catalog))


async def analysis_create(request):
    person = _reviewer(request)
    data = await _json_body(request)
    result = await run_in_threadpool(run_store, lambda s: tabular_service.create_order(s, person, data), write=True)
    return _response(result, 201)


async def analysis_order(request):
    _reviewer(request)
    id = request.path_params["id"]

    def detail(store):
        if not tabular_service.is_order(WorkOrders(store).get(id)):
            raise NotFound("No general analysis order with that ID")
        return _details(store, id)

    return _response(await run_in_threadpool(run_store, detail))


async def analysis_upload(request):
    _reviewer(request)
    params = request.path_params
    if "run_id" in params:
        run_id = _positive_integer(params["run_id"])
        name, content = await run_in_threadpool(run_store, lambda s: tabular_service.run_original(s, params["id"], run_id))
    else:
        name, content = await run_in_threadpool(run_store, lambda s: tabular_service.original(s, params["id"], params["kind"]))
    return Response(content.encode("utf-8"), media_type="application/octet-stream", headers={
        "Cache-Control": "private, no-store",
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
    })


async def analysis_action(request):
    person = _reviewer(request)
    data = await _json_body(request)
    id = request.path_params["id"]
    operation = tabular_service.run if request.url.path.endswith("/runs") else tabular_service.replace_control
    result = await run_in_threadpool(run_store, lambda s: operation(s, id, person, data), write=True)
    return _response(result, 201)


async def honey_catalog(request):
    _reviewer(request)
    return _response(await run_in_threadpool(run_store, honey_service.catalog))


async def honey_create(request):
    reviewer = _reviewer(request)
    if await _json_body(request):
        raise HTTPException(400, "Start the honey analysis with an empty JSON object.")
    data = await run_in_threadpool(run_store, lambda s: honey_service.create_order(s, reviewer), write=True)
    return _response(data, 201)


async def honey_order(request):
    _reviewer(request)
    order_id = request.path_params["id"]

    def detail(store):
        honey_service.require_order(WorkOrders(store).get(order_id))
        return _details(store, order_id)

    return _response(await run_in_threadpool(run_store, detail))


async def honey_run(request):
    reviewer = _reviewer(request)
    data = await _json_body(request)
    if set(data) not in ({"readings"}, {"readings", "submission"}) or (
        "submission" in data and type(data["submission"]) is not int
    ):
        raise HTTPException(400, "Supply duplicate simulated refractive-index readings and optionally the submission number.")
    order_id = request.path_params["id"]
    result = await run_in_threadpool(
        run_store, lambda s: honey_service.run(s, order_id, reviewer, data["readings"], data.get("submission")),
        write=True,
    )
    return _response(result, 201)


async def reference_catalog(request):
    _reviewer(request)
    return _response(await run_in_threadpool(references.catalog))


async def reference_search(request):
    _reviewer(request)
    instrument = request.query_params.get("instrument", "all")
    objective = request.query_params.get("q", "")
    return _response(await run_in_threadpool(references.search, instrument, objective))


async def reference_order(request):
    reviewer = _reviewer(request)
    data = await _json_body(request)
    created = await run_in_threadpool(
        run_store, lambda store: reference_orders.create_order(store, reviewer, data), write=True,
    )
    return _response(created, 201)


async def b12_order(request):
    reviewer = _reviewer(request)
    options = await _json_body(request)
    if set(options) - {"mode"} or options.get("mode", "example") not in ("agent", "example"):
        raise HTTPException(400, "Choose example or agent mode.")

    def create(store):
        data = b12_service.create_order(store, reviewer)
        if options.get("mode") != "agent":
            # Replay the versioned agent-written example as a new candidate for this lab.
            source = Path(__file__).with_name("b12_example.py").read_text(encoding="utf-8")
            orders = WorkOrders(store)
            worker = "Codex (bundled example)"
            orders.claim(data["id"], worker)
            submitted = orders.submit(data["id"], worker, {"source": source})
            if not submitted.passed:
                raise WorkOrderError("The example source failed verification against the pinned experiment.")
        return data

    data = await run_in_threadpool(run_store, create, write=True)
    return _response(data, 201)


async def b12_readings(request):
    reviewer = _reviewer(request)
    id = request.path_params["id"]
    if request.method == "GET":
        return _response(await run_in_threadpool(run_store, lambda store: b12_service.list_readings(store, id)))
    data = await _json_body(request)
    if set(data) != {"readings"}:
        raise HTTPException(400, "Supply three simulated absorbance readings.")
    try:
        values = await run_in_threadpool(
            run_store, lambda store: b12_service.save_readings(store, id, reviewer, data["readings"]), write=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return _response(values, 201)


async def b12_run(request):
    reviewer = _reviewer(request)
    id = request.path_params["id"]
    reading_id = _positive_integer(request.path_params["reading_id"])
    data = await _json_body(request)
    if set(data) != {"submission"} or type(data["submission"]) is not int or not 0 < data["submission"] < 2**63:
        raise HTTPException(400, "Supply the approved submission number.")
    result = await run_in_threadpool(
        run_store, lambda store: b12_service.run_readings(store, id, reading_id, reviewer, data["submission"]),
        write=True,
    )
    return _response(result)


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


reviewer_api = Starlette(routes=[
    Route("/api/session", session), Route("/api/login", login, methods=["POST"]),
    Route("/api/logout", logout, methods=["POST"]), Route("/api/orders", order_list, methods=["GET", "POST"]),
    Route("/api/orders/{id}", order_detail), Route("/api/orders/{id}/context", order_context),
    Route("/api/orders/{id}/{action}", decide, methods=["POST"]),
    Route("/api/experiments", experiment_list), Route("/api/experiments/{id:path}", experiment_detail),
    Route("/api/context/{kind}", context_put, methods=["POST"]), Route("/api/example", example, methods=["POST"]),
    Route("/api/references", reference_catalog), Route("/api/references/search", reference_search),
    Route("/api/references/orders", reference_order, methods=["POST"]),
    Route("/api/analysis", analysis_catalog), Route("/api/analysis/orders", analysis_create, methods=["POST"]),
    Route("/api/analysis/orders/{id}", analysis_order),
    Route("/api/analysis/orders/{id}/uploads/{kind}", analysis_upload),
    Route("/api/analysis/orders/{id}/runs/{run_id}/readings", analysis_upload),
    Route("/api/analysis/orders/{id}/runs", analysis_action, methods=["POST"]),
    Route("/api/analysis/orders/{id}/control", analysis_action, methods=["POST"]),
    Route("/api/honey", honey_catalog), Route("/api/honey/orders", honey_create, methods=["POST"]),
    Route("/api/honey/orders/{id}", honey_order),
    Route("/api/honey/orders/{id}/run", honey_run, methods=["POST"]),
    Route("/api/b12", b12_catalog), Route("/api/b12/orders", b12_order, methods=["POST"]),
    Route("/api/b12/orders/{id}/readings", b12_readings, methods=["GET", "POST"]),
    Route("/api/b12/orders/{id}/readings/{reading_id}/run", b12_run, methods=["POST"]),
], exception_handlers={cls: domain_error for cls in (HTTPException, ContextError, NotFound, WorkOrderError, HostedStorageError)})

mcp = make_mcp_app(run_store, lambda headers: _access().authenticate_agent(headers))


async def application(scope, receive, send):
    if scope["type"] == "http" and scope["path"] in ("/mcp", "/mcp/"):
        await mcp(scope, receive, send)
    else:
        await reviewer_api(scope, receive, send)


def make_portal(public_directory: Path):
    """Serve the reviewer and its static assets on the same origin as the API and MCP."""
    static = Starlette(
        routes=[Mount("/", app=StaticFiles(directory=public_directory, html=True))],
        exception_handlers={HTTPException: domain_error},
    )

    async def portal(scope, receive, send):
        if scope["type"] != "http" or scope["path"].split("/", 2)[1] in {"api", "mcp"}:
            await application(scope, receive, send)
        else:
            await static(scope, receive, send)

    return portal
