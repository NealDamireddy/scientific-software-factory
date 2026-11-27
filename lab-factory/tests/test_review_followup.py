import asyncio
from copy import deepcopy

import pytest

from labfactory import b12_service
from labfactory.store import Store
from labfactory.workorders import WorkOrders

from test_claim_recovery_acceptance import (
    EXAMPLES, FORMER, ORDER, PLAN, REPLACEMENT, REVIEWER,
    assert_refused, claim, cli, db, requeue_args, snapshot, submit, successful,
    worker_call,
)


@pytest.fixture
def reclaimed_after_rejection(db):
    original = claim(db)["claim_id"]
    submitted = submit(db)
    assert (submitted["passed"], submitted["status"], submitted["submission"]) == (
        True, "in_review", 1,
    )
    successful(cli(
        db, "wo", "reject", ORDER, "--submission", "1", "--by", REVIEWER,
        "--reason", "Use a different wavelength.",
    ))
    order, _, history = snapshot(db)
    assert (order.status, order.worker) == ("open", None)
    assert (history[-1]["event"], history[-1]["submission"]) == ("rejected", 1)
    current = claim(db)["claim_id"]
    assert current != original
    return db, original, current


def assert_submission_refused(db, response, before):
    after = snapshot(db)
    assert ("error" in response, after == before) == (True, True), (
        f"Expected refusal with unchanged order, submissions, and history. Got {response}"
    )


def assert_second_submission_in_review(db, response, artifact, before):
    assert (response.get("passed"), response.get("status"), response.get("submission")) == (
        True, "in_review", 2,
    ), response
    order, submissions, history = snapshot(db)
    assert (order.status, order.worker) == ("in_review", FORMER)
    assert submissions[:-1] == before[1]
    assert submissions[-1].artifact == artifact
    assert submissions[-1].artifact_digest == response["artifact_digest"]
    assert history[:-1] == before[2]
    event = history[-1]
    assert (event["event"], event["actor"], event["submission"]) == ("submitted", FORMER, 2)


def test_untagged_retry_of_rejected_artifact_cannot_reenter_review(reclaimed_after_rejection):
    db, _, _ = reclaimed_after_rejection
    before = snapshot(db)
    response = submit(db)
    assert_submission_refused(db, response, before)


def test_corrected_untagged_submission_after_same_worker_reclaim(reclaimed_after_rejection):
    db, _, _ = reclaimed_after_rejection
    corrected = deepcopy(PLAN)
    corrected["steps"][0]["settings"][0]["value"] = 560
    before = snapshot(db)
    assert_second_submission_in_review(db, submit(db, artifact=corrected), corrected, before)


def test_only_current_claim_tag_authorizes_tagged_retry(reclaimed_after_rejection):
    db, original, current = reclaimed_after_rejection
    before = snapshot(db)
    assert_refused(db, original)
    stale = worker_call(db, "submit_artifact", FORMER, PLAN, original)
    assert_submission_refused(db, stale, before)
    tagged = worker_call(db, "submit_artifact", FORMER, PLAN, current)
    assert_second_submission_in_review(db, tagged, PLAN, before)
    assert_refused(db, current)


def test_manual_requeue_requires_current_tag_even_for_changed_artifact(db):
    original = claim(db)["claim_id"]
    successful(cli(db, *requeue_args(original)))
    current = claim(db)["claim_id"]
    assert current != original
    revised = deepcopy(PLAN)
    revised["steps"][0]["settings"][0]["value"] = 560
    before = snapshot(db)
    assert_refused(db, original)
    assert_submission_refused(db, submit(db, artifact=revised), before)
    accepted = worker_call(db, "submit_artifact", FORMER, revised, current)
    assert (accepted.get("passed"), accepted.get("status"), accepted.get("submission")) == (
        True, "in_review", 1,
    ), accepted


def test_displaced_prebuilt_upload_leaves_order_claimable_after_reopen(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLES))
    from submit_example import submit as upload

    db = tmp_path / "prebuilt.db"
    source = (EXAMPLES.parent / "src" / "labfactory" / "b12_example.py").read_text(encoding="utf-8")
    with Store(db) as store:
        assert b12_service.create_order(store, REVIEWER)["id"] == ORDER

    displaced = claim(db, "example-agent")["claim_id"]
    successful(cli(db, *requeue_args(displaced)))
    before = snapshot(db)
    assert (before[0].status, before[0].worker) == ("open", None)

    # Each upload starts a new stdio server, and each snapshot reopens the database.
    assert asyncio.run(upload(db, ORDER, source)) == 1
    after_first_upload = snapshot(db)
    assert asyncio.run(upload(db, ORDER, source)) == 1
    after_second_upload = snapshot(db)
    replacement = worker_call(db, "claim_work_order", REPLACEMENT)

    assert (
        after_first_upload == before,
        after_second_upload == before,
        (replacement.get("status"), replacement.get("worker")),
    ) == (True, True, ("in_progress", REPLACEMENT)), (
        f"First upload left {after_first_upload[0]}, second left {after_second_upload[0]}, "
        f"replacement claim returned {replacement}"
    )
    assert replacement["claim_id"] != displaced
