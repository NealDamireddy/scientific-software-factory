"""Expose the agent interface over MCP on a local SQLite database."""

from mcp.server.fastmcp import FastMCP

from .agent import AgentTools
from .store import Store


def build_server(db_path: str) -> FastMCP:
    server = FastMCP("Lab Factory")

    @server.tool()
    def list_work_orders(status: str = "open") -> list[dict] | dict:
        """List work orders with the given status."""
        with Store(db_path) as store:
            return AgentTools(store).list_work_orders(status)

    @server.tool()
    def get_work_order_context(work_order_id: str) -> dict:
        """Read pinned context, artifact format, and feedback from the previous reviewer."""
        with Store(db_path) as store:
            return AgentTools(store).get_work_order_context(work_order_id)

    @server.tool()
    def claim_work_order(work_order_id: str, worker: str) -> dict:
        """Claim an open order under the worker's name."""
        with Store(db_path) as store:
            return AgentTools(store).claim_work_order(work_order_id, worker)

    @server.tool()
    def submit_artifact(work_order_id: str, worker: str, artifact: dict) -> dict:
        """Submit a candidate for the claimed order and return its numbered check results."""
        with Store(db_path) as store:
            return AgentTools(store).submit_artifact(work_order_id, worker, artifact)

    return server
