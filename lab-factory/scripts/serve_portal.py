"""Serve the combined Lab Factory portal on loopback with a local SQLite store."""

import argparse
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import uvicorn
from starlette.datastructures import MutableHeaders

from labfactory.hosted import make_portal


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

    await portal(scope, receive, send_with_headers)


def serve(database, port):
    database.parent.mkdir(parents=True, exist_ok=True)
    for key in ("VERCEL", "VERCEL_ENV"):
        os.environ.pop(key, None)
    os.environ["LABFACTORY_LOCAL_DB"] = str(database)
    os.environ["LABFACTORY_PUBLIC_REVIEW"] = "1"
    os.environ.setdefault("LABFACTORY_AGENTS", "{}")
    print(f"Lab Factory local reviewer and EVOLVE demos: http://127.0.0.1:{port}/\n"
          f"Local work orders: {database}", flush=True)
    uvicorn.run(local_application, host="127.0.0.1", port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--temporary", action="store_true", help="Discard this local session's orders on exit.")
    args = parser.parse_args()
    if not (PROJECT / "public/evolve/index.html").is_file():
        parser.error("Run npm run build:lab from the repository root to build the EVOLVE demos.")
    if args.temporary:
        with TemporaryDirectory(prefix="lab-portal-") as scratch:
            serve(Path(scratch) / "portal.sqlite3", args.port)
    else:
        serve(PROJECT.parent / "runs/lab-factory/portal.sqlite3", args.port)


if __name__ == "__main__":
    main()
