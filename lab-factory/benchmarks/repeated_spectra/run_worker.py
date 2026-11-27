"""Replay the spectroscopy request through the reviewer API and the real authenticated MCP worker."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from labfactory.hosted import application
from labfactory.tabular_worker import process


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    trial = json.loads(Path(__file__).with_name("trial.json").read_text())
    token = secrets.token_urlsafe()
    worker = "spectroscopy-replay"
    os.environ.update(
        LABFACTORY_LOCAL_DB=str(output / "lab.db"),
        LABFACTORY_PUBLIC_REVIEW="1",
        LABFACTORY_AGENTS=json.dumps({worker: hashlib.sha256(token.encode()).hexdigest()}),
    )
    origin = "http://localhost"
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(base_url=origin, transport=transport, headers={
        "Origin": origin, "Authorization": f"Bearer {token}",
    }) as client:
        for kind in ("lab", "experiment"):
            (await client.post(f"/api/context/{kind}", json=trial[kind])).raise_for_status()
        request = {"request_id": str(uuid4()), "objective": trial["objective"],
                   "project": {"experiment_id": trial["experiment"]["id"]}}
        created = await client.post("/api/analysis/apps", json=request)
        created.raise_for_status()
        key = created.json()["id"]
        url = f"/api/analysis/apps/{key}"
        async with streamable_http_client(origin + "/mcp", http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await process(session, key, worker)
                detail = (await client.get(url)).json()
                if detail["status"] != "needs_input":
                    raise ValueError(f"Expected a scientific clarification, received {detail['status']}")
                print(detail["history"][-1]["submission"]["question"], flush=True)
                (await client.post(url + "/answers", json={"turn": detail["turn"], "answer": trial["answer"]})).raise_for_status()
                await process(session, key, worker)
        detail = (await client.get(url)).json()
        (output / "transcript.json").write_text(json.dumps(detail, indent=2))
        if detail["status"] != "ready":
            raise ValueError(f"See transcript for the worker's next turn ({detail['status']})")
        result = await client.get(url + "/app")
        result.raise_for_status()
        if hashlib.sha256(result.content).hexdigest() != detail["artifact_digest"]:
            raise ValueError("Download differs from the stored artifact digest")
        (output / "app.html").write_bytes(result.content)
        print(f"Generated {output / 'app.html'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory to hold the local DB, transcript and app")
    asyncio.run(run(parser.parse_args().output.resolve()))
