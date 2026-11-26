"""One durable database transaction per hosted request."""

from collections.abc import Callable
from contextlib import closing, contextmanager
import os
import sqlite3
from typing import TypeVar
from urllib.parse import urlsplit

import httpx
import turso_serverless as turso
from turso_serverless.protocol import ProtocolError
from turso_serverless.session import Session, normalize_url

from .store import Store


T = TypeVar("T")


class HostedStorageError(RuntimeError):
    """The hosted database is unavailable or incorrectly configured."""


def _https_origin(url: str) -> str:
    try:
        parsed = urlsplit(normalize_url(url))
        parsed.port  # Reject malformed and out-of-range ports before creating a client.
    except (TypeError, ValueError):
        raise HostedStorageError("Turso requires an HTTPS database origin") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
        raise HostedStorageError("Turso requires an HTTPS database origin")
    return parsed.geturl()


class _HttpSession(Session):
    """Use the driver's Hrana encoding with a request-scoped, bounded HTTP client."""

    def __init__(self, url, token, client):
        self._origin = _https_origin(url)
        super().__init__(self._origin, auth_token=token)
        self._client = client
        self._lost = False

    def _post(self, path, body):
        if self._lost:
            raise ProtocolError("Database session interrupted")
        try:
            response = self._client.post(
                self._base_url + path, json=body, headers=self._headers(),
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            # A lost COMMIT response has an unknown outcome. Never replay the request.
            self._lost = True
            self._reset_stream()
            raise ProtocolError("Database session interrupted") from None

    def _update_stream(self, baton, base_url):
        if base_url:
            base_url = _https_origin(base_url)
            # Turso can pin the baton to a specific node in its own domain.
            target = urlsplit(base_url)
            trusted = urlsplit(self._origin)
            if target.netloc != trusted.netloc and not (
                trusted.hostname.endswith(".turso.io") and target.hostname.endswith(".turso.io")
                and target.port in (443, None)
            ):
                raise HostedStorageError("Unexpected Turso session origin")
        super()._update_stream(baton, base_url)


class _RequestStore(Store):
    def __init__(self, connection):
        self.connection = connection
        self._active = False
        self._write = False
        self._rollback_only = False
        self._initialize_schema()

    @contextmanager
    def _join(self):
        try:
            yield self.connection
        except BaseException:
            # AgentTools converts domain exceptions to error results. A caught
            # transition failure must still roll back all writes in this request.
            self._rollback_only = True
            raise

    def transaction(self):
        if not self._active:
            return super().transaction()  # First-use schema initialization.
        if not self._write:
            raise HostedStorageError("A write transaction is required")
        return self._join()

    def read_transaction(self):
        return self._join() if self._active else super().read_transaction()

    def run(self, operation: Callable[[Store], T], write: bool) -> T:
        self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        self._active = True
        self._write = write
        result = operation(self)
        if not self.connection.in_transaction:
            raise HostedStorageError("Database transaction ended unexpectedly")
        if self._rollback_only or not write:
            self.connection.rollback()
        else:
            self.connection.commit()
        return result


def run_store(operation: Callable[[Store], T], *, write: bool = False) -> T:
    """Run a synchronous operation against one snapshot, closing on every exit."""
    local_path = os.environ.get("LABFACTORY_LOCAL_DB")
    if local_path:
        if "VERCEL" in os.environ or "VERCEL_ENV" in os.environ:
            raise HostedStorageError("Vercel requires a durable remote database")
        with closing(sqlite3.connect(local_path, isolation_level=None, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            return _RequestStore(db).run(operation, write)

    url = os.environ.get("TURSO_DATABASE_URL")
    if not url and os.environ.get("BLOB_READ_WRITE_TOKEN"):
        from .blob_storage import run_blob_store

        return run_blob_store(operation, write=write)
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise HostedStorageError(
            "Configure private BLOB_READ_WRITE_TOKEN or both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN"
        )
    try:
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            session = _HttpSession(url, token, client)
            with closing(turso.Connection(session, isolation_level=None)) as db:
                db.row_factory = turso.Row
                return _RequestStore(db).run(operation, write)
    except turso.Error:
        # SQL errors can contain statement text. Leave details out of responses.
        raise HostedStorageError("The shared database could not complete the operation") from None
