"""Portable behavior suite for local and hosted repositories.

Run run_runtime_work_order_contract(make_repository) on an empty, isolated
backing store. Each zero-argument call must open a distinct repository against
that same store. The suite supplies its own structural principals and scope.
"""
import json
from pathlib import Path

from factory.runtime_work_order import ACTIONS, Scope


class TestPrincipal:
    def __init__(self, actor_id, *, is_human=False):
        self.actor_id = actor_id
        self.is_human = is_human

    def require(self, *, lab_id, project_id, action):
        if (lab_id, project_id) != ("lab", "project") or action not in ACTIONS.values():
            raise PermissionError("Outside grant")


def task_fixture():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("runtime_work_order.json").read_text())


def run_runtime_work_order_contract(make_repository):
    repo = make_repository()
    scope = Scope("lab", "project", "work-order")
    human = TestPrincipal("researcher", is_human=True)
    record = repo.apply(human, scope, "revise", task_fixture(), expected_version=0, key="draft")
    assert record["state"] == "draft"
    assert make_repository().history(human, scope) == [record]
