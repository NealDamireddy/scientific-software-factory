"""End-to-end acceptance through the ordinary reviewer API and independent MCP identity."""

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

from labfactory.context import canonical_digest
from labfactory.hosted import application
from labfactory.hosted_auth import password_hash, token_digest

ORIGIN = "https://localhost"
EXAMPLES = Path(__file__).parents[1] / "public" / "examples" / "tabular"
WORKER = "analyst"
TOKEN = "disposable-stock-example-token"


def example(name):
    info = next(row for row in json.loads((EXAMPLES / "index.json").read_text()) if row["folder"] == name)
    folder = EXAMPLES / info["folder"]
    qc = json.loads((folder / "control.json").read_text())
    return {key: info[key] for key in ("objective", "unit", "range_gate", "mapping")} | {
        "protocol": (folder / "protocol.md").read_text(), "protocol_name": "local-protocol.md",
        "csv": (folder / "readings.csv").read_text(), "csv_name": "private-export.csv",
        "control_expected": qc["expected"], "control_tolerance": qc["tolerance"],
    }


def candidate(source, synthetic_cases):
    tests = [{"label": f"Constructed sample {i}", "standards": standards, "signal": signal,
              "factor": factor, "expected": expected}
             for i, (standards, signal, factor, expected) in enumerate(synthetic_cases, 1)]
    return {"source": source, "explanation": "Apply the submitted method to one anonymous sample.", "tests": tests}


def calibrated_candidate():
    source = """def analyze(standards, signal, factor):
    signal_axis = column(standards, 0)
    known_axis = column(standards, 1)
    baseline = intercept(known_axis, signal_axis)
    response = slope(known_axis, signal_axis)
    return (signal - baseline) / response * factor
"""
    return candidate(source, [([[2, 0], [12, 4]], 7, 3, 6), ([[30, 1], [90, 3]], 60, 5, 10)])


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(tmp_path / "private.sqlite"))
    monkeypatch.setenv("LABFACTORY_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "a-disposable-session-key-for-testing")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"Reviewer": password_hash("disposable-password")}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({WORKER: token_digest(TOKEN)}))
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)


@asynccontextmanager
async def clients():
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}) as reviewer:
        (await reviewer.post("/api/login", json={"name": "Reviewer", "password": "disposable-password"})).raise_for_status()
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}) as author:
            async with streamable_http_client(ORIGIN + "/mcp", http_client=author) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    yield reviewer, author, session


async def call(session, tool, args):
    reply = await session.call_tool(tool, args)
    assert not reply.isError, reply.content
    return json.loads(reply.content[0].text)


def assert_private(agent_output, private_tokens):
    encoded = json.dumps(agent_output, ensure_ascii=False)
    for token in private_tokens:
        assert str(token) not in encoded


async def caffeine_workflow():
    request = example("caffeine")
    # The two reference controls here are independent mock certificates. Their
    # sample IDs, readings and assigned values are absent from the public example.
    request["csv"] = request["csv"].replace("QC-A,control,1640", "PRIVATE-24Z,control,1770.7")
    request["control_expected"] = 17.307
    secrets = ["PRIVATE-24Z", "private-export.csv", 1770.7, 17.307, "Coffee A", "Coffee B"]
    correct = calibrated_candidate()
    wrong = candidate("def analyze(standards, signal, factor):\n    return signal * factor\n",
                      [([[2, 0], [12, 4]], 7, 3, 21), ([[30, 1], [90, 3]], 60, 5, 300)])
    async with clients() as (reviewer, author, session):
        new = await reviewer.post("/api/analysis/orders", json=request)
        order_id = new.raise_for_status().json()["id"]
        path = "/api/analysis/orders/" + order_id
        decision = "/api/orders/" + order_id + "/approve"
        decision_body = {"expected_reviewer": "Reviewer", "submission": 1}
        key = {"work_order_id": order_id}
        args = {**key, "worker": WORKER}
        assert (await author.get(path)).status_code == 401
        assert (await author.get(path + "/uploads/readings")).status_code == 401
        assert (await reviewer.get(path + "/uploads/readings")).content == request["csv"].encode()
        ctx = await call(session, "get_work_order_context", key)
        assert_private(ctx, secrets)
        assert ctx["analysis"]["protocol"] == request["protocol"]
        assert len(ctx["analysis"]["standards"]) == 5
        assert (await call(session, "claim_work_order", args))["status"] == "in_progress"

        failed = await call(session, "submit_artifact", {**args, "artifact": wrong})
        assert not failed["passed"] and failed["submission"] == 1
        assert_private(failed, secrets)
        review = (await reviewer.get(path)).raise_for_status().json()
        rejected, = review["submissions"]
        assert rejected["artifact_digest"] == canonical_digest(wrong)
        assert all(r["passed"] for r in rejected["results"] if r["name"].startswith("Agent test"))
        assert not rejected["control"]["passed"] and rejected["control"]["expected"] == 17.307
        assert rejected["control"]["predicted"] == pytest.approx(3541.4)
        assert (await reviewer.post(decision, json=decision_body)).status_code == 409
        assert (await reviewer.post(path + "/runs", json={"submission": 1})).status_code == 409

        again = await call(session, "submit_artifact", {**args, "artifact": correct})
        assert "fresh" in again["error"].lower()
        assert_private(await call(session, "get_work_order_context", key), secrets)
        fresh = {"signal": 1478.2, "factor": 2, "expected": 14.382, "tolerance": 0.15}
        recovered = (await reviewer.post(path + "/control", json=fresh)).raise_for_status().json()
        assert recovered["edition"] == 2
        secrets.extend([1478.2, 14.382])
        assert_private(await call(session, "get_work_order_context", key), secrets)
        fixed = await call(session, "submit_artifact", {**args, "artifact": correct})
        assert_private(fixed, secrets)
        assert fixed["passed"] and fixed["submission"] == 2 and fixed["status"] == "in_review"
        assert (await reviewer.post(decision, json=decision_body)).status_code == 409
        (await reviewer.post(decision, json={**decision_body, "submission": 2})).raise_for_status()

        old = (await reviewer.post(path + "/runs", json={"submission": 2})).raise_for_status().json()
        assert old["release_control_edition"] == 2
        assert old["control"]["edition"] == 1 and old["control"]["passed"]
        assert old["control"]["signal"] == 1770.7 and old["control"]["expected"] == request["control_expected"]
        assert [r["value"] for r in old["results"]] == pytest.approx([24, 45])
        assert old["artifact_digest"] == canonical_digest(correct)
        assert old["csv_digest"] == sha256(request["csv"].encode()).hexdigest()
        changed_csv = """sample,role,area,concentration,dilution
S1,standard,50,0,1
S2,standard,2050,5,1
S3,standard,4050,10,1
S4,standard,8050,20,1
QC-B,control,4250,,2
New coffee,unknown,2450,,5
Outside,unknown,9001,,1
"""
        next_batch = {"submission": 2, "csv_name": "fresh.csv", "csv": changed_csv,
                      "control_expected": 21, "control_tolerance": 0.04}
        good = (await reviewer.post(path + "/runs", json=next_batch)).raise_for_status().json()
        assert good["control"]["passed"] and good["artifact_digest"] == old["artifact_digest"]
        assert good["csv_digest"] != old["csv_digest"] and good["protocol_digest"] == old["protocol_digest"]
        assert [r["value"] for r in good["results"]] == [30.0, None]
        assert "range" in good["results"][1]["reason"]
        # Keep the known certificate fixed and change only the observed QC signal.
        bad_batch = {**next_batch, "csv": changed_csv.replace("control,4250", "control,4370")}
        withheld = (await reviewer.post(path + "/runs", json=bad_batch)).raise_for_status().json()
        assert not withheld["control"]["passed"] and withheld["status"] == "withheld" and not withheld["results"]
        assert (await reviewer.post(path + "/runs", json=bad_batch)).json()["id"] == withheld["id"]


def test_caffeine_from_private_intake_to_verified_release_and_batch_reuse(configured):
    asyncio.run(caffeine_workflow())


async def density_workflow():
    request = example("density")
    source = "def analyze(standards, signal, factor):\n    return signal / factor\n"
    analysis = candidate(source, [([], 6, 2, 3), ([], 4.5, 3, 1.5)])
    async with clients() as (reviewer, _, session):
        id_ = (await reviewer.post("/api/analysis/orders", json=request)).raise_for_status().json()["id"]
        path = "/api/analysis/orders/" + id_
        args = {"work_order_id": id_, "worker": WORKER}
        ctx = await call(session, "get_work_order_context", {"work_order_id": id_})
        assert ctx["analysis"]["mapping"] == request["mapping"] and not ctx["analysis"]["range_gate"]
        assert_private(ctx, ["Check liquid", "Liquid A", "Liquid B"])
        await call(session, "claim_work_order", args)
        sub = await call(session, "submit_artifact", {**args, "artifact": analysis})
        assert sub["passed"] and sub["status"] == "in_review"
        (await reviewer.post("/api/orders/" + id_ + "/approve",
                             json={"submission": 1, "expected_reviewer": "Reviewer"})).raise_for_status()
        result = (await reviewer.post(path + "/runs", json={"submission": 1})).raise_for_status().json()
        assert result["unit"] == "g/mL" and result["control"]["passed"]
        assert [row["value"] for row in result["results"]] == pytest.approx([1.08, 0.8])
        assert result["artifact_digest"] == canonical_digest(analysis)
        assert (await reviewer.get(path)).json()["runs"][0]["id"] == result["id"]


def test_density_from_different_protocol_and_headers_through_identical_endpoints(configured):
    asyncio.run(density_workflow())


@pytest.mark.parametrize("public", [False, True], ids=["named", "public"])
def test_linked_uploads_follow_released_pins_across_context_edits(
        configured, monkeypatch, public, uvvis_lab_dict, b12_experiment_dict):
    if public:
        monkeypatch.setenv("LABFACTORY_PUBLIC_REVIEW", "1")
    asyncio.run(linked_uploads(uvvis_lab_dict, b12_experiment_dict))


async def linked_uploads(lab, exp):
    async with clients() as (reviewer, _, session):
        async def post(path, data):
            return (await reviewer.post(path, json=data)).raise_for_status().json()

        await post("/api/context/lab", lab)
        await post("/api/context/experiment", exp)
        procedure = (await post("/api/orders", {"kind": "procedure", "experiment_id": exp["id"],
                                                "objective": "Review optical handling"}))["id"]
        path = "/api/analysis/orders"
        request = dict(example("caffeine"), procedure_order_id=procedure, request_id=str(uuid4()))
        assert (await reviewer.post(path, json=request)).status_code == 409
        args = {"work_order_id": procedure, "worker": WORKER}
        await call(session, "claim_work_order", args)
        artifact = {"steps": [{"text": "Record the optical reading.", "citations": ["sop-cuvette"]}]}
        await call(session, "submit_artifact", {**args, "artifact": artifact})
        assert (await reviewer.post(path, json=request)).status_code == 409
        await post("/api/orders/" + procedure + "/reject", {"submission": 1, "reason": "Clarify the instruction."})
        await call(session, "claim_work_order", args)
        artifact["steps"][0]["text"] = "Record the blank-corrected reading."
        await call(session, "submit_artifact", {**args, "artifact": artifact})
        await post("/api/orders/" + procedure + "/approve", {"submission": 2})
        pin = {"order_id": procedure, "submission": 2, "artifact_digest": canonical_digest(artifact),
               "experiment_id": exp["id"], "experiment_revision": 1, "lab_id": lab["id"], "lab_revision": 1}
        before = await post(path, request)
        revised_lab = {**lab, "documents": [{**lab["documents"][0], "text": "Revised SOP."}]}
        assert (await post("/api/context/lab", revised_lab))["revision"] == 2
        assert (await post("/api/context/experiment", {**exp, "goal": "A new goal."}))["revision"] == 2
        assert await post(path, request) == before
        after = await post(path, {**request, "request_id": str(uuid4())})
        assert before != after
        for upload in (before, after):
            detail_path = path + "/" + upload["id"]
            assert (await reviewer.get(detail_path)).json()["analysis"]["procedure"] == pin
            ctx = (await call(session, "get_work_order_context", {"work_order_id": upload["id"]}))["analysis"]
            assert ctx["procedure"] == pin
            assert ctx["procedure_context"]["lab"] == lab and ctx["procedure_context"]["experiment"] == exp
            assert artifact["steps"][0]["text"] in ctx["procedure_context"]["instructions"]
            assert_private(ctx, ["QC-A", "private-export.csv", "Coffee A"])
        args = {"work_order_id": after["id"], "worker": WORKER}
        await call(session, "claim_work_order", args)
        assert (await call(session, "submit_artifact", {**args, "artifact": calibrated_candidate()}))["passed"]
        await post("/api/orders/" + after["id"] + "/approve", {"submission": 1})
        detail_path = path + "/" + after["id"]
        receipt = await post(detail_path + "/runs", {"submission": 1})
        assert receipt["procedure"] == pin
        assert (await reviewer.get(detail_path)).json()["runs"] == [receipt]
        assert await post(detail_path + "/runs", {"submission": 1}) == receipt
        for changes, status in [({"procedure_order_id": after["id"], "request_id": str(uuid4())}, 409),
                                ({"procedure_order_id": "WO-missing", "request_id": str(uuid4())}, 404),
                                ({"procedure_order_id": after["id"]}, 409), ({"procedure": pin}, 400)]:
            assert (await reviewer.post(path, json={**request, **changes})).status_code == status
