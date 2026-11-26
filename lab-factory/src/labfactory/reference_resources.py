"""Read-only MCP views of the same catalog available to reviewers."""
import json
from urllib.parse import unquote

from . import references


def register(server):
    @server.resource("labfactory://references/catalog", mime_type="application/json")
    def reference_catalog() -> str:
        """List instrument and technique IDs, collection sizes and example searches."""
        return json.dumps(references.catalog(), ensure_ascii=False)

    @server.resource("labfactory://references/search/{instrument}/{query}", mime_type="application/json")
    def find_references(instrument: str, query: str) -> str:
        """Search by instrument ID (or all) and URL-encoded experiment objective."""
        return json.dumps(references.search(instrument, unquote(query)), ensure_ascii=False)

    @server.resource("labfactory://references/source/{source_id}", mime_type="application/json")
    def get_reference(source_id: str) -> str:
        """Read a curated record, its original publisher link and evidence locator."""
        return json.dumps(references.source(source_id), ensure_ascii=False)
