"""Shared repository semantics over scoped transactions and exact revision lookup."""
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from .catalog_contract import (
    APPROVE, PROPOSE, READ, RECORD_EVIDENCE, ApprovalReceipt, CatalogRecord, Kind, Principal, RevisionPin,
)
from .catalog_validation import authorize, cited_source_ids, encode_payload, validate_revision, validate_stream
from .context import digest
from .context_repository import RevisionConflict


class CatalogTransaction(Protocol):
    """Bound to one lab/kind/record stream for the transaction's entire lifetime."""

    def read(self, revision: int | None) -> CatalogRecord | None: ...
    def history(self) -> tuple[CatalogRecord, ...]: ...
    def has_source(self, revision_id: str) -> bool:
        """Whether this lab owns this exact revision of kind 'source'."""
        ...
    def append(self, record: CatalogRecord, encoded: str) -> None: ...
    def add_receipt(self, receipt: ApprovalReceipt) -> None: ...


class CatalogDomainRepository(ABC):
    @abstractmethod
    def _transaction(self, kind: Kind, lab_id: str, record_id: str, *,
                     write: bool) -> AbstractContextManager[CatalogTransaction]:
        """On writes, serialize this stream including its empty state before yielding.

        Commit on successful exit, roll back on exceptions. Reads include the
        persisted receipt and return detached records. History is oldest first.
        """
        ...

    @abstractmethod
    def _read_by_id(self, kind: Kind, lab_id: str, revision_id: str) -> CatalogRecord | None:
        """Filter on all three selectors and include the exact revision's receipt."""
        ...

    def get_by_id(self, kind: Kind, lab_id: str, revision_id: str, *, principal: Principal) -> CatalogRecord:
        authorize(principal, lab_id, READ)
        validate_stream(kind, lab_id, revision_id)
        record = self._read_by_id(kind, lab_id, revision_id)
        if record is None:
            raise KeyError("No matching catalog record")
        return record

    def get(self, kind: Kind, lab_id: str, record_id: str, *, revision: int | None = None,
            principal: Principal) -> CatalogRecord:
        authorize(principal, lab_id, READ)
        validate_stream(kind, lab_id, record_id)
        if revision is not None:
            validate_revision(revision, minimum=1)
        with self._transaction(kind, lab_id, record_id, write=False) as tx:
            record = tx.read(revision)
        if record is None:
            raise KeyError("No matching catalog record")
        return record

    def history(self, kind: Kind, lab_id: str, record_id: str, *,
                principal: Principal) -> tuple[CatalogRecord, ...]:
        authorize(principal, lab_id, READ)
        validate_stream(kind, lab_id, record_id)
        with self._transaction(kind, lab_id, record_id, write=False) as tx:
            records = tx.history()
        if not records:
            raise KeyError("No matching catalog record")
        return records

    def save(self, kind: Kind, lab_id: str, record_id: str, payload: dict, *,
             expected_revision: int, principal: Principal) -> CatalogRecord:
        authorize(principal, lab_id, RECORD_EVIDENCE if kind == "evidence" else PROPOSE)
        validate_stream(kind, lab_id, record_id)
        validate_revision(expected_revision, minimum=0)
        encoded, snapshot = encode_payload(kind, payload)
        with self._transaction(kind, lab_id, record_id, write=True) as tx:
            previous = tx.read(None)
            current = previous.pin.revision if previous else 0
            if current != expected_revision:
                raise RevisionConflict(f"{kind} expected_revision={expected_revision}, current={current}; reload and retry")
            if kind == "catalog":
                for source_id in cited_source_ids(snapshot):
                    if not tx.has_source(source_id):
                        raise ValueError("citation must identify a source revision in the owning lab")
            pin = RevisionPin(lab_id, kind, record_id, current + 1, str(uuid4()), digest(encoded.encode()))
            predecessor_id = previous.pin.revision_id if previous else None
            record = CatalogRecord(pin, principal.actor_id, datetime.now(timezone.utc).isoformat(),
                                   predecessor_id, snapshot, None)
            tx.append(record, encoded)
        return record

    def approve(self, pin: RevisionPin, *, principal: Principal) -> ApprovalReceipt:
        authorize(principal, pin.lab_id, APPROVE)
        if principal.is_human is not True:
            raise PermissionError("Catalog approval requires a human")
        validate_stream(pin.kind, pin.lab_id, pin.record_id)
        if pin.kind != "catalog":
            raise ValueError("Only catalog revisions take approval receipts")
        validate_revision(pin.revision, minimum=1)
        with self._transaction(pin.kind, pin.lab_id, pin.record_id, write=True) as tx:
            current = tx.read(None)
            if current is None:
                raise KeyError("No matching catalog record")
            if current.pin != pin:
                raise RevisionConflict("Obsolete or mismatched catalog pin; reload and retry")
            if current.approval:
                if current.approval.approver != principal.actor_id:
                    raise RevisionConflict("An approval receipt already exists for this revision")
                return current.approval
            gaps = current.payload["unresolved_gaps"]
            if gaps:
                raise ValueError(f"Unresolved evidence gaps: {gaps}")
            receipt = ApprovalReceipt(pin, principal.actor_id, datetime.now(timezone.utc).isoformat())
            tx.add_receipt(receipt)
        return receipt
