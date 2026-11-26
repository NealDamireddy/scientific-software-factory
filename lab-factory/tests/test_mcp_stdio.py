import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from labfactory.cli import main


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TOOLS = {"list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact"}


@asynccontextmanager
async def agent_session(db):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "labfactory", "--db", str(db), "serve"],
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


async def call(session, name, args):
    result = await session.call_tool(name, args)
    assert not result.isError, result.content
    payload = json.loads(result.content[0].text)
    assert "error" not in payload, payload
    return payload


def test_mcp_stdio_round_trip(tmp_path, capsys, uvvis_lab_dict, b12_experiment_dict):
    db = tmp_path / "lab.db"

    def cli(*args, expected=0):
        assert main(["--db", str(db), *args]) == expected
        return capsys.readouterr()

    cli("lab", "put", str(EXAMPLES / "uvvis-lab.json"))
    cli("experiment", "put", str(EXAMPLES / "b12-experiment.json"))
    order = cli("wo", "create", "b12-vial-a", "--kind", "run_plan", "--objective", "Read absorbance")
    assert order.out.strip() == "WO-1"

    latest_lab = deepcopy(uvvis_lab_dict)
    latest_lab["instruments"][0]["parameters"][0]["maximum"] = 900
    latest_experiment = {**b12_experiment_dict, "goal": "Read a new reference."}
    for kind, data in [("lab", latest_lab), ("experiment", latest_experiment)]:
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert "revision 2" in cli(kind, "put", str(path)).out

    order_id = {"work_order_id": "WO-1"}

    async def first_agent():
        async with agent_session(db) as session:
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == TOOLS
            codex = {**order_id, "worker": "codex"}
            await call(session, "claim_work_order", codex)
            ctx = await call(session, "get_work_order_context", order_id)
            assert ctx["lab"] == uvvis_lab_dict
            assert ctx["experiment"] == b12_experiment_dict
            valid_plan = ctx["artifact_example"]
            invalid = deepcopy(valid_plan)
            invalid["steps"][0]["settings"][0]["value"] = 800
            failed = await call(session, "submit_artifact", {**codex, "artifact": invalid})
            assert failed["submission"] == 1
            assert not failed["passed"]
            assert failed["status"] == "in_progress"
            assert any("outside [400, 700] nm" in r["detail"] for r in failed["results"] if not r["passed"])
            ctx = await call(session, "get_work_order_context", order_id)
            assert ctx["work_order"]["worker"] == "codex"
            corrected = await call(session, "submit_artifact", {**codex, "artifact": valid_plan})
            assert corrected["passed"] and corrected["status"] == "in_review"
            assert corrected["submission"] == 2
            return valid_plan

    rejected_plan = asyncio.run(first_agent())
    reason = "use 2x dilution"
    rendered = cli("wo", "show", "WO-1").out
    assert "awaiting review: submission 2" in rendered
    assert "550 nm" in rendered
    cli("wo", "reject", "WO-1", "--submission", "2", "--by", "Neal", "--reason", reason)

    async def next_agent():
        async with agent_session(db) as session:
            claude = {**order_id, "worker": "claude"}
            await call(session, "claim_work_order", claude)
            ctx = await call(session, "get_work_order_context", order_id)
            previous = ctx["previous_rejection"]
            assert previous == {"artifact": rejected_plan, "reason": reason, "by": "Neal", "submission": 2}
            revised = deepcopy(previous["artifact"])
            revised["steps"][0]["settings"].append({"parameter": "integration_time", "value": 2, "unit": "s"})
            submitted = await call(session, "submit_artifact", {**claude, "artifact": revised})
            canonical = json.dumps(revised, sort_keys=True, separators=(",", ":"))
            fingerprint = sha256(canonical.encode()).hexdigest()
            assert submitted["artifact_digest"] == fingerprint
            assert submitted["submission"] == 3 and submitted["passed"]
            assert submitted["status"] == "in_review"
            return fingerprint

    fingerprint = asyncio.run(next_agent())
    stale = cli("wo", "approve", "WO-1", "--submission", "2", "--by", "Neal", expected=1)
    assert "submission 2 is not the latest (latest is 3)" in stale.err
    assert "awaiting review: submission 3" in cli("wo", "show", "WO-1").out
    cli("wo", "approve", "WO-1", "--submission", "3", "--by", "Neal")
    released = cli("wo", "show", "WO-1").out
    assert "released: submission 3 by Neal" in released
    assert fingerprint in released


def test_stdio_reference_discovery_and_encoded_search(tmp_path):
    async def read():
        async with agent_session(tmp_path / "references.db") as session:
            resources = await session.list_resources()
            assert "labfactory://references/catalog" in {str(r.uri) for r in resources.resources}
            templates = await session.list_resource_templates()
            assert {t.uriTemplate for t in templates.resourceTemplates} == {
                "labfactory://references/search/{instrument}/{query}", "labfactory://references/source/{source_id}",
            }
            found = await session.read_resource("labfactory://references/search/all/caffeine%20in%20coffee")
            evidence = json.loads(found.contents[0].text)
            assert evidence["query"] == "caffeine in coffee"
            key = "agilent-caffeine-in-coffee-din-20481"
            assert key in {r["id"] for r in evidence["findings"]}
            item = await session.read_resource("labfactory://references/source/" + key)
            assert json.loads(item.contents[0].text)["digest"] == next(
                r["digest"] for r in evidence["findings"] if r["id"] == key)
    asyncio.run(read())
