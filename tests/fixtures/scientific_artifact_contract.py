"""Adapter conformance entry point.

Supply make_repository(principal) -> ScientificArtifactRepository. All calls in
one scenario must open the same initially empty durable store. A new callable
invocation represents a fresh adapter (reopen). Use an isolated store per run.
"""

from collections.abc import Callable
from dataclasses import dataclass
from unittest import TestCase

from factory.scientific_artifact import DECIDE, READ, WRITE, Principal, ScientificArtifactRepository

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
