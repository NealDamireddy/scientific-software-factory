"""Transport-independent runtime work-order contract, version 1.

A stream is identified by (lab_id, project_id, work_order_id). Versions start at
one. Each successful command appends one immutable record. Versions double as
local identifiers for revisions, reviews, findings, resolutions and attempts.
Use the exact stream when following a reference. History of a missing stream
is empty. Reopening a repository is safe while other processes are working.

Command payloads (required keys unless indicated):

* revise: objective, scope (strings), dependencies, requirements, blueprints
  (lists of pins), specification (pin), acceptance_criteria, permitted_outputs
  (string lists), context (the service-filtered JSON snapshot). A pin is
  {"id": str, "sha256": 64 lowercase hex digits}. Output state is draft.
  predecessor identifies the previous revision, or None.
* review: task_version, kind (readiness, implementation_alignment,
  scientific_reasoning, reproducibility), candidate_sha256 (null for
  readiness), predecessor (null or failed/interrupted review version),
  optional model and prompt_version. The principal owns the queued review.
* review_state: review (start version), state (running/completed/failed/
  interrupted), evidence (list of references). Terminal outcomes are final.
* finding: review, classification (blocking/advisory), rationale, evidence.
* resolve: finding, rationale, evidence. Human-only, one resolution per finding.
* accept: task_version, kind (readiness/engineering), candidate_sha256 (null
  for readiness), rationale, evidence. Human-only receipt for these pins.
* claim: task_version, route (configured/external), predecessor (null for
  first assignment or the latest terminal coding attempt start version).
  The principal is the coding identity. The initial state is pending.
* coding_state: attempt (claim version), state (running/completed/failed/
  interrupted), evidence. Only the claiming identity reports its state.
* interrupt: attempt (claim or review start version), evidence. Trusted
  recovery services call this for each confirmed uncertain live attempt at
  startup, using the observed stream version. Never infer completion.

All evidence is a list of nonblank reference strings. State reports may have
an empty evidence list. Review/attempt status and child records inherit the
exact task, context and candidate pins of their target. Retries link to the
prior start version. A task revision always starts its own readiness history.
The caller evaluates eligibility and chooses the current candidate outside this
repository. Superseded task revisions cannot receive new claims or decisions.

apply authorizes before lookup. Identical (actor, command, payload) retries
under the same per-stream key return the original record, including after
later writes. Key reuse with other content, stale expected_version or an
incompatible transition raises RevisionConflict. Invalid shape raises
ValueError. Unauthorized calls raise PermissionError. Expected version zero
creates a stream. Every append atomically compares the current version.

Adapter contract: RuntimeRecordStore.read returns ordered detached records.
append must atomically insert record.version at exactly expected_version + 1
only if the persisted head equals expected_version, or raise RevisionConflict.
Unique (scope, version) and (scope, key) constraints fence races. Adapters can
reuse RuntimeWorkOrders from factory.runtime_work_order_domain for all command
semantics. SQLiteRuntimeWorkOrderRepository(db_path) lives in
factory.runtime_work_order_sqlite. Its migration owns only runtime_* objects
and a domain-local schema version. Initializing an adapter never changes
PRAGMA user_version or performs recovery.
"""
from dataclasses import dataclass
from typing import Protocol, TypedDict

from .context_repository import RevisionConflict

__all__ = ["ACTIONS", "Principal", "Scope", "RuntimeRecord", "RuntimeRecordStore",
           "RuntimeWorkOrderRepository", "RevisionConflict"]

ACTIONS = {name: f"runtime.{name}" for name in (
    "history", "revise", "review", "review_state", "finding", "resolve",
    "accept", "claim", "coding_state", "interrupt",
)}


class Principal(Protocol):
    actor_id: str
    is_human: bool

    def require(self, *, lab_id: str, project_id: str | None, action: str) -> None: ...


@dataclass(frozen=True)
class Scope:
    lab_id: str
    project_id: str
    work_order_id: str


class RuntimeRecord(TypedDict):
    version: int
    command: str
    key: str
    actor_id: str
    created_at: str
    payload: dict
    task_version: int
    task_sha256: str
    context_sha256: str
    candidate_sha256: str | None
    predecessor: int | None
    state: str | None


class RuntimeRecordStore(Protocol):
    """Internal trusted persistence port. Per-stream versions are contiguous."""

    def read(self, scope: Scope) -> list[RuntimeRecord]: ...

    def append(self, scope: Scope, record: RuntimeRecord, *, expected_version: int) -> None: ...


class RuntimeWorkOrderRepository(Protocol):
    def history(self, principal: Principal, scope: Scope) -> list[RuntimeRecord]: ...

    def apply(self, principal: Principal, scope: Scope, command: str, payload: dict,
              *, expected_version: int, key: str) -> RuntimeRecord: ...
