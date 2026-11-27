"""Serve an extracted Lab Factory Vercel entry point with loopback Blob storage.

Use the lab-factory venv. Supply synthetic LABFACTORY_AGENTS, LABFACTORY_REVIEWERS,
LABFACTORY_SESSION_KEY (or LABFACTORY_PUBLIC_REVIEW=1), and the local sidecar's
BLOB_READ_WRITE_TOKEN in the process environment. TLS mode models Vercel HTTPS.
Plain loopback HTTP uses VERCEL_ENV=preview for the local acceptance runner.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import httpx
import uvicorn


BLOB_PATH = re.compile(r"labfactory/(?:lab\.sqlite3|uploads/[0-9a-f]{64})")
PRIVATE_HOST = "trial.private.blob.vercel-storage.com"


class LoopbackBlobTransport(httpx.BaseTransport):
    """Redirect only the operations issued by the pinned private Blob adapters."""

    def __init__(self, port):
        self.port = port
        self.http = httpx.HTTPTransport(trust_env=False)

    def handle_request(self, request):
        url = request.url
        is_read = (request.method == "GET" and url.host == PRIVATE_HOST
                   and BLOB_PATH.fullmatch(url.path.lstrip("/"))
                   and url.params.multi_items() == [("cache", "0")])
        is_write = (request.method == "PUT" and url.host == "vercel.com"
                    and url.path == "/api/blob/" and len(url.params.multi_items()) == 1
                    and BLOB_PATH.fullmatch(url.params.get("pathname", "")))
        if url.scheme != "https" or url.port is not None or not (is_read or is_write):
            raise httpx.TransportError("Unexpected operation on the trial Blob client", request=request)
        local_url = url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        forwarded = httpx.Request(
            request.method, local_url, headers=request.headers,
            stream=request.stream, extensions=request.extensions,
        )
        return self.http.handle_request(forwarded)

    def close(self):
        self.http.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="extracted pinned lab-factory directory")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--blob-port", type=int, required=True)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    args = parser.parse_args()
    if not (0 < args.port < 65536 and 0 < args.blob_port < 65536 and args.port != args.blob_port):
        parser.error("supply two distinct TCP ports between 1 and 65535")
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be supplied together")
    if not re.fullmatch(r"vercel_blob_rw_trial_[A-Za-z0-9_-]+", os.getenv("BLOB_READ_WRITE_TOKEN", "")):
        parser.error("supply the local sidecar's synthetic trial token")
    keep = {
        "PATH", "TMPDIR", "LANG", "BLOB_READ_WRITE_TOKEN", "LABFACTORY_AGENTS",
        "LABFACTORY_REVIEWERS", "LABFACTORY_SESSION_KEY", "LABFACTORY_PUBLIC_REVIEW",
    }
    for key in list(os.environ):
        if key not in keep:
            del os.environ[key]
    os.environ["VERCEL_ENV"] = "preview"
    if args.tls_cert:
        os.environ.update({
            "VERCEL": "1", "VERCEL_URL": f"127.0.0.1:{args.port}",
            "LABFACTORY_PUBLIC_ORIGIN": f"https://localhost:{args.port}",
        })
    else:
        os.environ["LABFACTORY_PUBLIC_ORIGIN"] = f"http://127.0.0.1:{args.port}"
    sys.dont_write_bytecode = True
    root = args.source_root.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("lab_factory_vercel_entrypoint", root / "api" / "index.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    from labfactory import blob_storage, tabular_files

    def make_client(**kwargs):
        return httpx.Client(**kwargs, trust_env=False, transport=LoopbackBlobTransport(args.blob_port))

    # Replace only the client factory used by these modules. Their URL validation,
    # HTTP payloads, CAS logic, and reads/writes all run as committed.
    for adapter in (blob_storage, tabular_files):
        if Path(adapter.__file__).resolve().parent != root / "src" / "labfactory":
            raise RuntimeError("Blob adapter did not resolve from the selected source root")
        adapter.httpx = SimpleNamespace(Client=make_client, HTTPError=httpx.HTTPError)
    uvicorn.run(
        entry.app, host="127.0.0.1", port=args.port, access_log=False,
        ssl_certfile=str(args.tls_cert) if args.tls_cert else None,
        ssl_keyfile=str(args.tls_key) if args.tls_key else None,
    )


if __name__ == "__main__":
    main()
