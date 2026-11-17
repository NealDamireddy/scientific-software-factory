"""Adapter conformance entry point.

Supply make_repository(principal) -> ScientificArtifactRepository. All calls in
one scenario must open the same initially empty durable store. A new callable
invocation represents a fresh adapter (reopen). Use an isolated store per run.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from unittest import TestCase

from factory.context_repository import RevisionConflict
from factory.scientific_artifact import (
    DECIDE, READ, WRITE, Principal, ReconciliationMarker, ScientificArtifactRepository, artifact_digest,
)

RepositoryFactory = Callable[[Principal], ScientificArtifactRepository]


@dataclass
class FixturePrincipal:
    actor_id: str = "researcher"
    is_human: bool = True
    actions: tuple[str, ...] = (READ, WRITE, DECIDE)
    scope: tuple[str, str] = ("lab", "project")

    def require(self, *, lab_id, project_id, action):
        if (lab_id, project_id) != self.scope or action not in self.actions:
            raise PermissionError("No grant")


def check_repository(case: TestCase, make_repository: RepositoryFactory) -> None:
    principal = FixturePrincipal()
    repo = make_repository(principal)
    payload = {"knowledge_kind": "protocol", "source_id": "assay-protocol",
               "source_revision": "v1", "content_ref": "evidence/protocol-v1",
               "evidence_gaps": ["temperature range"]}
    knowledge = repo.save(*principal.scope, "knowledge", "protocol", payload, expected_revision=0)
    case.assertEqual(knowledge.payload, payload)
    case.assertEqual(knowledge.author_id, principal.actor_id)
    case.assertEqual(knowledge.state, "draft")
    case.assertEqual(make_repository(principal).get(*principal.scope, "knowledge", "protocol"), knowledge)

    # A validation service can pass incomplete scientific fields for a draft.
    requirement = repo.save(*principal.scope, "requirement", "r", {"objective": "quantify absorbance"},
                            references=(knowledge.pin,), expected_revision=0)
    blueprint = repo.save(*principal.scope, "blueprint", "b", {"questions": ["matrix effect?"]},
                          references=(requirement.pin,), expected_revision=0)
    basis = (knowledge.pin, requirement.pin, blueprint.pin)
    spec_body = {"objective": "measure absorbance", "work_type": "exploratory",
                 "unresolved_questions": [], "limitations": ["virtual instrument"]}
    spec = repo.save(*principal.scope, "specification", "s", spec_body, references=basis, expected_revision=0)
    case.assertEqual(spec.state, "draft")
    case.assertEqual(spec.pin.sha256, artifact_digest(spec_body, basis))
    case.assertEqual(spec.references, basis)
    case.assertIsNone(spec.predecessor)

    editor = make_repository(FixturePrincipal("editor"))
    next_req = editor.save(*principal.scope, "requirement", "r", {"objective": "corrected absorbance"},
                           references=(knowledge.pin,), expected_revision=1)
    case.assertEqual(next_req.predecessor, requirement.pin)
    marker = ReconciliationMarker(blueprint.pin, requirement.pin, next_req.pin)
    case.assertEqual(repo.reconciliation(blueprint.pin), (marker,))
    late = repo.save(*principal.scope, "blueprint", "late", {}, expected_revision=0, references=(requirement.pin,))
    case.assertEqual(repo.reconciliation(late.pin), (replace(marker, blueprint=late.pin),))

    decider = make_repository(FixturePrincipal("approver", actions=(DECIDE,)))
    rejected = decider.decide(spec.pin, "rejected", rationale="Needs independent check",
                              limitations=("simulated only",))
    approved = decider.decide(spec.pin, "approved", rationale="Checked protocol", limitations=("simulated only",))
    case.assertEqual(approved.specification, spec.pin)
    case.assertEqual(approved.actor_id, "approver")
    case.assertEqual(approved.decision, "approved")
    case.assertEqual(approved.limitations, ("simulated only",))
    case.assertEqual(approved.rationale, "Checked protocol")
    case.assertEqual(datetime.fromisoformat(approved.decided_at).utcoffset(), timedelta(0))

    next_spec = editor.save(*principal.scope, "specification", "s", dict(spec_body, limitations=[]),
                            references=basis, expected_revision=1)
    with case.assertRaises(RevisionConflict):
        editor.save(*principal.scope, "specification", "s", {}, expected_revision=1)
    with case.assertRaises(RevisionConflict):
        decider.decide(spec.pin, "approved", rationale="Late approval")
    reopened = make_repository(principal)
    case.assertEqual(reopened.history(*principal.scope, "specification", "s"),
                     (replace(spec, state="approved"), next_spec))
    case.assertEqual(next_spec.state, "draft")
    case.assertEqual(next_spec.author_id, "editor")
    case.assertEqual(next_spec.predecessor, spec.pin)
    case.assertEqual(reopened.decisions(spec.pin), (rejected, approved))
    case.assertEqual(reopened.decisions(next_spec.pin), ())
    case.assertEqual(reopened.get(*principal.scope, "knowledge", "protocol", revision=1), knowledge)
    case.assertEqual(reopened.get(*principal.scope, "blueprint", "b").references, (requirement.pin,))
    case.assertEqual(reopened.reconciliation(blueprint.pin), (marker,))

    # Bad or unavailable references must leave no partial revision or receipt.
    for bad, error in ((replace(requirement.pin, sha256="0" * 64), ValueError),
                       (replace(requirement.pin, revision=99), KeyError),
                       (replace(requirement.pin, project_id="other"), PermissionError),
                       (replace(requirement.pin, lab_id="other"), PermissionError)):
        with case.assertRaises(error):
            repo.save(*principal.scope, "specification", "s", {}, expected_revision=2,
                      references=(knowledge.pin, bad))
    case.assertEqual(repo.get(*principal.scope, "specification", "s"), next_spec)
    with case.assertRaises(ValueError):
        decider.decide(replace(next_spec.pin, sha256="0" * 64), "approved", rationale="Wrong digest")
    case.assertEqual(repo.decisions(next_spec.pin), ())

    # Identical local names across projects must still resolve to separate rows.
    outsider = FixturePrincipal("outsider", scope=("lab", "other"))
    remote = make_repository(outsider)
    other = remote.save(*outsider.scope, "knowledge", "protocol", {}, expected_revision=0)
    case.assertNotEqual(other.pin, knowledge.pin)
    for artifact_id in ("protocol", "absent"):
        with case.assertRaises(PermissionError):
            remote.get(*principal.scope, "knowledge", artifact_id)
        with case.assertRaises(PermissionError):
            remote.history(*principal.scope, "knowledge", artifact_id)
    with case.assertRaises(PermissionError):
        remote.decisions(spec.pin)
    with case.assertRaises(PermissionError):
        remote.reconciliation(blueprint.pin)
    with case.assertRaises(PermissionError):
        remote.decide(next_spec.pin, "approved", rationale="Unauthorized scope")

    reader = FixturePrincipal("reader", actions=(READ,))
    read_only = make_repository(reader)
    with case.assertRaises(PermissionError):
        read_only.save(*principal.scope, "knowledge", "protocol", {"actor_id": "approver"}, expected_revision=1)
    with case.assertRaises(PermissionError):
        read_only.decide(next_spec.pin, "approved", rationale="No decision grant")
    agent = make_repository(FixturePrincipal("worker", is_human=False))
    with case.assertRaises(PermissionError):
        agent.decide(next_spec.pin, "approved", rationale="Agent cannot decide")
    writer = make_repository(FixturePrincipal(actions=(WRITE,)))
    with case.assertRaises(PermissionError):
        writer.save(*principal.scope, "blueprint", "b", {}, expected_revision=1, references=(requirement.pin,))
    reader.actions = ()
    with case.assertRaises(PermissionError):
        read_only.decisions(next_spec.pin)
