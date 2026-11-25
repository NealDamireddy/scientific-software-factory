"""Public repository boundary for lab-private instrument knowledge (WO-28).

Payload examples live in tests.fixtures.catalog_examples. All adapters use canonical
JSON payload digests. Source references in claims use immutable same-lab source
revision IDs plus locations. Authorities, timestamps and receipts are server-owned.
"""
from dataclasses import dataclass
from typing import Literal, Protocol

Kind = Literal["catalog", "source", "evidence"]
READ = "catalog.read"
PROPOSE = "catalog.propose"  # Creates catalog and source revisions.
RECORD_EVIDENCE = "catalog.record_evidence"
APPROVE = "catalog.approve"


class Principal(Protocol):
    actor_id: str
    is_human: bool

    def require(self, *, lab_id: str, project_id: str | None, action: str) -> None: ...


@dataclass(frozen=True)
class RevisionPin:
    lab_id: str
    kind: Kind
    record_id: str
    revision: int
    revision_id: str
    sha256: str


@dataclass(frozen=True)
class ApprovalReceipt:
    pin: RevisionPin
    approver: str
    approved_at: str  # timezone-aware ISO 8601


@dataclass(frozen=True)
class CatalogRecord:
    pin: RevisionPin
    author: str
    created_at: str
    predecessor_id: str | None
    payload: dict
    approval: ApprovalReceipt | None

    @property
    def state(self) -> Literal["draft", "approved"] | None:
        if self.pin.kind == "catalog":
            return "approved" if self.approval else "draft"
        return None


class CatalogRepository(Protocol):
    """Every call checks principal.require(lab_id=..., project_id=None, action=...).

    Missing authorized lookups raise KeyError. Invalid data raises ValueError.
    Stale writes/pins and conflicting receipt writes raise RevisionConflict from
    factory.lab_context.context_repository. Denied calls raise PermissionError before lookup.
    """

    def save(self, kind: Kind, lab_id: str, record_id: str, payload: dict, *,
             expected_revision: int, principal: Principal) -> CatalogRecord:
        """Append to this stream. Creation requires 0, edits require the current revision."""
        ...

    def get(self, kind: Kind, lab_id: str, record_id: str, *, revision: int | None = None,
            principal: Principal) -> CatalogRecord:
        """Read the specified revision, or the head when revision is omitted."""
        ...

    def get_by_id(self, kind: Kind, lab_id: str, revision_id: str, *, principal: Principal) -> CatalogRecord:
        """Resolve an exact revision ID, including a source revision cited by a claim."""
        ...

    def history(self, kind: Kind, lab_id: str, record_id: str, *,
                principal: Principal) -> tuple[CatalogRecord, ...]:
        """All revisions in ascending order. An unknown stream raises KeyError."""
        ...

    def approve(self, pin: RevisionPin, *, principal: Principal) -> ApprovalReceipt:
        """Approve exact current catalog pin after curation validation.

        Recorded unresolved gaps block a new receipt and are identified in the error.
        A human approver retry on the same head returns their original receipt.
        A different approver cannot replace the original decision.
        """
        ...
