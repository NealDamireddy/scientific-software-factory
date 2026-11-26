"""Authenticated, stateless Streamable HTTP transport for the four agent operations."""

import json
import logging
import os
from urllib.parse import urlsplit

from anyio import to_thread
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route, Router
from starlette.types import ASGIApp, Receive, Scope, Send

from .agent import AgentTools


logger = logging.getLogger(__name__)


def _transport_security() -> TransportSecuritySettings:
    origins = {
        f"https://{os.environ[key]}"
        for key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL")
        if os.environ.get(key)
    }
    if custom := os.environ.get("LABFACTORY_PUBLIC_ORIGIN"):
        origins.add(custom.rstrip("/"))
    hosts = {urlsplit(origin).netloc for origin in origins}
    if not os.environ.get("VERCEL"):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            hosts.update((host, host + ":*"))
            origins.update(("http://" + host, "http://" + host + ":*"))
    return TransportSecuritySettings(allowed_hosts=sorted(hosts), allowed_origins=sorted(origins))


def _artifact_limit_error(artifact):
    try:
        encoded = json.dumps(artifact, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError):
        return "artifact must contain valid UTF-8 JSON"
    if len(encoded) > 128 * 1024:
        return "hosted artifacts can contain at most 128 KiB of compact UTF-8 JSON"
    steps = artifact.get("steps")
    if isinstance(steps, list) and len(steps) > 256:
        return "hosted artifacts can contain at most 256 steps"

    # Instrument and command names appear on several check results per step.
    def check_action(action):
        for key in ("instrument_id", "command"):
            if isinstance(action.get(key), str) and len(action[key]) > 256:
                return f"{key} can contain at most 256 characters"
        if isinstance(action.get("settings"), list) and len(action["settings"]) > 256:
            return "each hosted action can contain at most 256 settings"
        return None

    if error := check_action(artifact):
        return error
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                action = step.get("action", step)
                if isinstance(action, dict) and (error := check_action(action)):
                    return error
    return None


def _agent_server(run_store, agent_name: str, security: TransportSecuritySettings) -> FastMCP:
    server = FastMCP(
        "Lab Factory", stateless_http=True, json_response=True, transport_security=security,
    )

    async def stored(operation, *, write=False):
        try:
            return await to_thread.run_sync(
                lambda: run_store(lambda store: operation(AgentTools(store)), write=write)
            )
        except Exception as exc:
            # Database/provider errors can contain connection details. Keep them off the wire.
            logger.error("Agent store operation failed (%s)", type(exc).__name__)
            if write:
                raise RuntimeError(
                    "The write could not be confirmed. Read the work order with "
                    "get_work_order_context and check its status. If still in progress, ask a reviewer "
                    "to check the latest numbered submission before retrying."
                ) from None
            raise RuntimeError("The lab store is unavailable. Retry the read.") from None

    @server.tool()
    async def list_work_orders(status: str = "open") -> list[dict] | dict:
        """List work orders with the given status."""
        return await stored(lambda agent: agent.list_work_orders(status))

    @server.tool()
    async def get_work_order_context(work_order_id: str) -> dict:
        """Read pinned context, artifact format, and feedback from the previous reviewer."""
        return await stored(lambda agent: agent.get_work_order_context(work_order_id))

    @server.tool()
    async def claim_work_order(work_order_id: str, worker: str) -> dict:
        """Claim an open order using the name assigned to your agent credential."""
        if worker != agent_name:
            return {"error": "worker must match the authenticated agent name"}
        return await stored(lambda agent: agent.claim_work_order(work_order_id, worker), write=True)

    @server.tool()
    async def submit_artifact(work_order_id: str, worker: str, artifact: dict) -> dict:
        """Submit a candidate as its claiming agent and return numbered check results."""
        if worker != agent_name:
            return {"error": "worker must match the authenticated agent name"}
        if error := _artifact_limit_error(artifact):
            return {"error": error}
        return await stored(lambda agent: agent.submit_artifact(work_order_id, worker, artifact), write=True)

    return server


def make_mcp_app(run_store, authenticate_agent) -> ASGIApp:
    """Serve POST /mcp with a credential-bound identity and a request-local MCP lifespan."""
    security = _transport_security()

    class AgentEndpoint:
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            headers = Headers(scope=scope)
            credentials = headers.getlist("authorization")
            name = None
            if len(credentials) == 1:
                scheme, _, token = credentials[0].partition(" ")
                if scheme.lower() == "bearer" and token.strip():
                    try:
                        name = authenticate_agent(headers)
                    except HTTPException as exc:
                        if exc.status_code != 503:
                            raise
                        unavailable = JSONResponse(
                            {"error": "Agent authentication is unavailable."},
                            status_code=503, headers={"Cache-Control": "no-store"},
                        )
                        await unavailable(scope, receive, send)
                        return
            if not name:
                denied = JSONResponse(
                    {"error": "A valid agent bearer token is required."}, status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="Lab Factory"', "Cache-Control": "no-store"},
                )
                await denied(scope, receive, send)
                return
            # A Vercel invocation may have no ASGI startup/shutdown events. Start and
            # close this request's own manager, even during concurrent warm invocations.
            server = _agent_server(run_store, name, security)
            server.streamable_http_app()
            async with server.session_manager.run():
                await server.session_manager.handle_request(scope, receive, send)

    endpoint = AgentEndpoint()
    return Router(routes=[Route(path, endpoint, methods=["POST"]) for path in ("/mcp", "/mcp/")])
