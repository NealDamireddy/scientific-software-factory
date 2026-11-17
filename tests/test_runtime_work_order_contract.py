"""Portable behavior suite for local and hosted repositories.

Run run_runtime_work_order_contract(make_repository) on an empty, isolated
backing store. Each zero-argument call must open a distinct repository against
that same store. The suite supplies its own structural principals and scopes.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
from threading import Barrier
from unittest import TestCase

from factory.context import digest
from factory.context_repository import canonical_json
from factory.runtime_work_order import ACTIONS, RevisionConflict, Scope

CHECK = TestCase()
CANDIDATE = "d" * 64


class FixturePrincipal:
    def __init__(self, actor_id, commands, *, is_human=False, lab="lab", project="project"):
        self.actor_id = actor_id
        self.is_human = is_human
        self.grants = {ACTIONS[command] for command in commands}
        self.scope = lab, project

    def require(self, *, lab_id, project_id, action):
        if (lab_id, project_id) != self.scope or action not in self.grants:
            raise PermissionError("Outside grant")


def task_fixture():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("runtime_work_order.json").read_text())


class Scenario:
    def __init__(self, make_repository, order):
        self.open = make_repository
        self.repo = make_repository()
        self.scope = Scope("lab", "project", order)
        self.human = FixturePrincipal("researcher", ["history", "revise", "resolve", "accept"], is_human=True)
        self.reviewer = FixturePrincipal("reviewer", ["review", "finding", "review_state"])
        self.coder = FixturePrincipal("worker", ["claim", "coding_state"])
        self.service = FixturePrincipal("service", ["supersede", "submission_validated", "interrupt"])
        self.expected = []

    def add(self, actor, command, **payload):
        version = len(self.expected)
        result = self.repo.apply(actor, self.scope, command, payload,
                                 expected_version=version, key=f"{command}-{version}")
        CHECK.assertEqual(result["actor_id"], actor.actor_id)
        CHECK.assertEqual(result["version"], version + 1)
        CHECK.assertEqual(result["payload"], payload)
        CHECK.assertIsNotNone(datetime.fromisoformat(result["created_at"]).utcoffset())
        self.expected.append(result)
        return result

    def reject(self, error, actor, command, **payload):
        with CHECK.assertRaises(error):
            self.repo.apply(actor, self.scope, command, payload, key="rejected",
                            expected_version=len(self.expected))
        CHECK.assertEqual(self.repo.history(self.human, self.scope), self.expected)

    def reopen(self):
        self.repo = self.open()
        CHECK.assertEqual(self.repo.history(self.human, self.scope), self.expected)


def _revision_and_review(make_repository):
    s = Scenario(make_repository, "reviews")
    original = task_fixture()
    revision = s.add(s.human, "revise", **original)
    CHECK.assertEqual(revision["state"], "draft")
    CHECK.assertEqual(revision["context_sha256"], digest(canonical_json(original["context"]).encode()))
    CHECK.assertIsNone(revision["predecessor"])
    original["context"].clear()
    review_payload = dict(task_version=1, kind="scientific_reasoning", candidate_sha256=CANDIDATE,
                          model="model-id", prompt_version="r2", predecessor=None)
    review = s.add(s.reviewer, "review", **review_payload)
    CHECK.assertEqual(review["state"], "queued")
    target = review["version"]
    s.add(s.reviewer, "review_state", review=target, state="running", evidence=[])
    finding = s.add(s.reviewer, "finding", review=target, classification="blocking",
                    rationale="Include the mg/L conversion", evidence=["line-20"])
    s.add(s.reviewer, "review_state", review=target, state="failed", evidence=["worker-exit"])
    s.reopen()
    retry = {**review_payload, "predecessor": target}
    s.reject(RevisionConflict, s.reviewer, "review", **{**retry, "candidate_sha256": "e" * 64})
    s.reject(RevisionConflict, s.reviewer, "review", **{**retry, "kind": "reproducibility"})
    successor = s.add(s.reviewer, "review", **retry)
    CHECK.assertEqual(successor["predecessor"], target)
    s.reject(RevisionConflict, s.reviewer, "review", **retry)
    s.add(s.reviewer, "review_state", review=successor["version"], state="completed", evidence=["report.json"])
    decision = dict(finding=finding["version"], rationale="Checked corrected units", evidence=["unit-test"])
    agent = FixturePrincipal("agent", ["resolve", "accept"])
    s.reject(PermissionError, agent, "resolve", **decision)
    s.reject(ValueError, s.human, "resolve", **{**decision, "evidence": []})
    resolution = s.add(s.human, "resolve", **decision)
    s.reject(RevisionConflict, s.human, "resolve", **decision)
    acceptance = dict(task_version=1, kind="engineering", candidate_sha256=CANDIDATE,
                      rationale="Reviewed units and evidence", evidence=["human-review"])
    s.reject(PermissionError, agent, "accept", **acceptance)
    receipt = s.add(s.human, "accept", **acceptance)
    for child in (review, finding, resolution, receipt):
        CHECK.assertEqual(child["candidate_sha256"], CANDIDATE)
        CHECK.assertEqual(child["task_sha256"], revision["task_sha256"])
        CHECK.assertEqual(child["context_sha256"], revision["context_sha256"])
    updated = s.add(s.human, "revise", **{**task_fixture(), "context": {"instrument": "uvvis-2"}})
    CHECK.assertEqual((updated["predecessor"], updated["state"]), (1, "draft"))
    CHECK.assertNotEqual(updated["context_sha256"], revision["context_sha256"])
    CHECK.assertNotEqual(updated["task_sha256"], revision["task_sha256"])
    s.reject(RevisionConflict, s.human, "accept", **acceptance)
    s.reject(RevisionConflict, s.reviewer, "review", **retry)
    readiness = s.add(s.reviewer, "review", task_version=updated["version"], kind="readiness",
                      candidate_sha256=None, predecessor=None)
    s.add(s.service, "interrupt", attempt=readiness["version"], evidence=["restart-1"])
    s.add(s.reviewer, "review", **{**readiness["payload"], "predecessor": readiness["version"]})
    s.reopen()
    CHECK.assertEqual(s.expected[0]["payload"], task_fixture())


def _coding_history(make_repository):
    s = Scenario(make_repository, "coding")
    s.add(s.human, "revise", **task_fixture())
    payload = dict(task_version=1, route="configured", predecessor=None)
    claim = s.add(s.coder, "claim", **payload)
    CHECK.assertEqual(claim["state"], "assigned")
    other = FixturePrincipal("external-worker", ["claim", "coding_state"])
    s.reject(RevisionConflict, other, "claim", **payload)
    target = claim["version"]
    s.reject(PermissionError, other, "coding_state", attempt=target, state="failed", evidence=[])
    s.add(s.coder, "coding_state", attempt=target, state="running", evidence=[])
    completion = s.add(s.coder, "coding_state", attempt=target, state="completion_claim", evidence=["worker-log"])
    CHECK.assertEqual(completion["state"], "running")
    s.reject(ValueError, s.coder, "coding_state", attempt=target, state="submitted", evidence=[])
    s.reject(PermissionError, s.coder, "submission_validated", attempt=target, candidate_sha256=CANDIDATE,
             evidence=["self-report"])
    s.reject(RevisionConflict, other, "claim", **{**payload, "predecessor": target})
    s.reopen()
    interrupted = s.add(s.service, "interrupt", attempt=target, evidence=["restart-1"])
    CHECK.assertEqual(interrupted["state"], "interrupted")
    s.reject(RevisionConflict, other, "claim", **payload)
    second = s.add(other, "claim", **{**payload, "route": "external", "predecessor": target})
    s.reject(RevisionConflict, s.coder, "coding_state", attempt=target, state="running", evidence=[])
    s.add(other, "coding_state", attempt=second["version"], state="failed", evidence=["connection-lost"])
    s.reopen()
    third = s.add(s.coder, "claim", **{**payload, "predecessor": second["version"]})
    retired = s.add(s.service, "supersede", attempt=third["version"], evidence=["reassigned"])
    CHECK.assertEqual(retired["state"], "superseded")
    fourth = s.add(other, "claim", **{**payload, "predecessor": third["version"], "route": "external"})
    submitted = s.add(s.service, "submission_validated", attempt=fourth["version"],
                      candidate_sha256=CANDIDATE, evidence=["validated-manifest"])
    CHECK.assertEqual((submitted["state"], submitted["candidate_sha256"]), ("submitted", CANDIDATE))
    s.reject(RevisionConflict, s.service, "interrupt", attempt=fourth["version"], evidence=["restart-2"])
    s.reopen()


def _access_and_replay(make_repository):
    s = Scenario(make_repository, "replay")
    task = task_fixture()
    record = s.add(s.human, "revise", **task)
    key = record["key"]
    s.add(s.human, "revise", **{**task, "scope": "Second revision"})
    s.reopen()
    apply = s.repo.apply
    reordered = dict(reversed(list(task.items())))
    CHECK.assertEqual(apply(s.human, s.scope, "revise", reordered, expected_version=0, key=key), record)
    for changed in ({**task, "scope": "Changed"}, {**task, "actor_id": "other"}):
        with CHECK.assertRaises(RevisionConflict):
            apply(s.human, s.scope, "revise", changed, expected_version=0, key=key)
    impostor = FixturePrincipal("other", ["revise"])
    with CHECK.assertRaises(RevisionConflict):
        apply(impostor, s.scope, "revise", task, expected_version=0, key=key)
    s.reject(ValueError, s.human, "revise", **{**task, "context": {"invalid": object()}})
    for field in ("actor_id", "lab_id", "project_id", "state"):
        s.reject(ValueError, s.human, "revise", **{**task, field: "injected"})
    with CHECK.assertRaises(RevisionConflict):
        apply(s.human, s.scope, "revise", task, expected_version=1, key="stale")
    with CHECK.assertRaises(PermissionError):
        s.repo.history(s.human, Scope("other", "project", s.scope.work_order_id))
    s.human.grants.discard(ACTIONS["revise"])
    with CHECK.assertRaises(PermissionError):
        apply(s.human, s.scope, "revise", task, expected_version=0, key=key)
    for lab, project in (("lab", "other"), ("other", "project")):
        separate = FixturePrincipal("researcher", ["history", "revise"], lab=lab, project=project)
        scope = Scope(lab, project, s.scope.work_order_id)
        CHECK.assertEqual(s.repo.history(separate, scope), [])
        foreign = apply(separate, scope, "revise", task, expected_version=0, key=key)
        CHECK.assertNotEqual(foreign["task_sha256"], record["task_sha256"])
    s.reopen()


def _race(make_repository, *, identical):
    s = Scenario(make_repository, f"race-{identical}")
    s.add(s.human, "revise", **task_fixture())
    barrier = Barrier(2)

    def claim(index):
        repo = make_repository()
        actor = s.coder if identical else FixturePrincipal(f"worker-{index}", ["claim"])
        key = "claim" if identical else f"claim-{index}"
        barrier.wait(timeout=20)
        try:
            return repo.apply(actor, s.scope, "claim", dict(task_version=1, route="external", predecessor=None),
                              expected_version=1, key=key)
        except RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [r for r in pool.map(claim, range(2)) if r is not None]
    CHECK.assertEqual(len(winners), 2 if identical else 1)
    CHECK.assertEqual(winners[0], winners[-1])
    s.expected.append(winners[0])
    s.reopen()


def run_runtime_work_order_contract(make_repository):
    _revision_and_review(make_repository)
    _coding_history(make_repository)
    _access_and_replay(make_repository)
    _race(make_repository, identical=True)
    _race(make_repository, identical=False)
