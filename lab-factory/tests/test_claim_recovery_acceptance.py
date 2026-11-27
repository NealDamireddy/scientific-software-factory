import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
from threading import Barrier

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from labfactory.agent import AgentTools
from labfactory.artifacts import ARTIFACT_EXAMPLES
from labfactory.cli import main
from labfactory.store import Store
from labfactory.workorders import WorkOrders


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
ORDER = "WO-1"
FORMER = "worker-original"
REPLACEMENT = "worker-replacement"
REVIEWER = "Ada Reviewer"
REASON = "The original worker stopped responding."
PLAN = ARTIFACT_EXAMPLES["run_plan"]


def cli(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "labfactory", "--db", str(db), *args],
        cwd=db.parent, capture_output=True, text=True, timeout=15,
    )


def successful(result):
    assert result.returncode == 0, result.stderr
    return result.stdout


def show(db):
    return successful(cli(db, "wo", "show", ORDER))


def active_claim(db):
    displayed = show(db)
    match = re.search(r"^claim: ([0-9]+)$", displayed, re.MULTILINE)
    assert match, f"wo show did not display the active claim ID:\n{displayed}"
    return int(match[1])


def requeue_args(claim_id, reason=REASON):
    return ["wo", "requeue", ORDER, "--claim", str(claim_id), "--by", REVIEWER, "--reason", reason]


def worker_call(db, name, *args):
    with Store(db) as store:
        return getattr(AgentTools(store), name)(ORDER, *args)


def claim(db, worker=FORMER):
    result = worker_call(db, "claim_work_order", worker)
    assert result.get("status") == "in_progress", result
    return result


def submit(db, worker=FORMER, artifact=PLAN):
    return worker_call(db, "submit_artifact", worker, artifact)


def snapshot(db):
    with Store(db) as store:
        orders = WorkOrders(store)
        return orders.get(ORDER), orders.submissions(ORDER), orders.history(ORDER)


def assert_recovery_event(history, previous):
    assert history[:-1] == previous
    event = history[-1]
    assert event["event"] == "requeued"
    assert event["actor"] == REVIEWER
    recorded = json.dumps(event, ensure_ascii=False)
    assert FORMER in recorded
    assert REASON in recorded


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "factory.db"
    successful(cli(path, "lab", "put", str(EXAMPLES / "uvvis-lab.json")))
    successful(cli(path, "experiment", "put", str(EXAMPLES / "b12-experiment.json")))
    assert successful(cli(path, "wo", "create", "b12-vial-a", "--kind", "run_plan",
                          "--objective", "Read the vial")).strip() == ORDER
    return path


@pytest.mark.parametrize("has_failed_submission", [False, True], ids=["before-submit", "after-failed-checks"])
def test_recovery_preserves_pins_and_submission_history(
    db, uvvis_lab_dict, b12_experiment_dict, has_failed_submission,
):
    original_context = worker_call(db, "get_work_order_context")
    claim(db)
    if has_failed_submission:
        invalid = deepcopy(PLAN)
        invalid["steps"][0]["settings"][0]["value"] = 800
        failed = submit(db, artifact=invalid)
        assert (failed["submission"], failed["passed"], failed["status"]) == (1, False, "in_progress")
    claim_id = active_claim(db)

    uvvis_lab_dict["instruments"][0]["parameters"][0]["maximum"] = 500
    b12_experiment_dict["goal"] = "Read a new reference."
    for kind, record in [("lab", uvvis_lab_dict), ("experiment", b12_experiment_dict)]:
        revision_file = db.parent / f"{kind}-revision-2.json"
        revision_file.write_text(json.dumps(record), encoding="utf-8")
        assert "revision 2" in successful(cli(db, kind, "put", str(revision_file)))

    _, prior_submissions, prior_history = snapshot(db)
    successful(cli(db, *requeue_args(claim_id)))

    reopened, submissions, history = snapshot(db)
    assert (reopened.id, reopened.status, reopened.worker) == (ORDER, "open", None)
    assert (reopened.lab_revision, reopened.experiment_revision) == (1, 1)
    assert submissions == prior_submissions
    assert_recovery_event(history, prior_history)
    assert "claim:" not in show(db)
    assert ORDER in successful(cli(db, "wo", "list", "--status", "open")).split()

    before_late_submit = snapshot(db)
    assert "error" in submit(db)
    assert snapshot(db) == before_late_submit

    claim(db, REPLACEMENT)
    assert active_claim(db) != claim_id
    context = worker_call(db, "get_work_order_context")
    for key in ("lab", "experiment"):
        assert context[key] == original_context[key]

    before_late_submit = snapshot(db)
    assert "error" in submit(db)
    assert snapshot(db) == before_late_submit

    accepted = submit(db, REPLACEMENT)
    assert accepted["passed"] and accepted["status"] == "in_review", accepted
    assert accepted["submission"] == (2 if has_failed_submission else 1)
    _, final_submissions, final_history = snapshot(db)
    assert final_submissions[:-1] == prior_submissions
    assert final_submissions[-1].artifact_digest == accepted["artifact_digest"]
    assert final_history[:-2] == history
    assert [(event["event"], event["actor"]) for event in final_history[-2:]] == [
        ("claimed", REPLACEMENT), ("submitted", REPLACEMENT),
    ]


def assert_refused(db, claim_id, reason=REASON):
    before = snapshot(db)
    result = cli(db, *requeue_args(claim_id, reason))
    assert result.returncode == 1 and result.stderr.startswith("error: "), result.stderr
    assert snapshot(db) == before


def test_requeue_rejects_open_order(db):
    assert_refused(db, 1)


def test_requeue_rejects_order_already_in_review(db):
    claim(db)
    claim_id = active_claim(db)
    assert submit(db)["passed"]
    assert_refused(db, claim_id)


def test_requeue_rejects_unknown_claim_and_blank_reason(db):
    claim(db)
    claim_id = active_claim(db)
    assert_refused(db, claim_id + 1)
    assert_refused(db, claim_id, reason="   ")
    assert active_claim(db) == claim_id


@pytest.mark.parametrize("next_worker", [FORMER, REPLACEMENT], ids=["same-worker", "different-worker"])
def test_stale_operator_request_cannot_release_new_claim(db, next_worker):
    claim(db)
    original = active_claim(db)
    successful(cli(db, *requeue_args(original)))
    assert_refused(db, original)

    replacement_claim = claim(db, next_worker)
    current = active_claim(db)
    assert current != original
    assert_refused(db, original)
    assert active_claim(db) == current
    assert worker_call(db, "submit_artifact", next_worker, PLAN, replacement_claim["claim_id"])["passed"]


def test_requeue_racing_passing_submission_has_one_winner(db):
    claim(db)
    claim_id = active_claim(db)
    _, _, prior_history = snapshot(db)
    start = Barrier(2, timeout=10)

    def recover():
        start.wait()
        return main(["--db", str(db), *requeue_args(claim_id)])

    def pass_checks():
        start.wait()
        return submit(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(recover)
        submission = pool.submit(pass_checks)
        recovery_code = recovery.result(timeout=15)
        response = submission.result(timeout=15)

    order, submissions, history = snapshot(db)
    if recovery_code == 0:
        assert "error" in response
        assert (order.status, order.worker, submissions) == ("open", None, [])
        assert_recovery_event(history, prior_history)
    else:
        assert recovery_code == 1
        assert response["passed"] and response["submission"] == 1
        assert order.status == "in_review"
        booked, = submissions
        assert booked.artifact_digest == response["artifact_digest"]
        assert history[:-1] == prior_history
        event = history[-1]
        assert (event["event"], event["actor"], event["submission"]) == ("submitted", FORMER, 1)


def test_recovery_stays_outside_worker_mcp(db):
    claim(db)
    before = snapshot(db)

    async def probe():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "labfactory", "--db", str(db), "serve"],
            cwd=db.parent,
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    "list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact",
                }
                denied = await session.call_tool("requeue_work_order", {
                    "work_order_id": ORDER, "claim_id": 1, "by": REVIEWER, "reason": REASON,
                })
                assert denied.isError, denied.content

    asyncio.run(probe())
    assert snapshot(db) == before
