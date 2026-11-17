"""Transport-independent scientific artifact repository contract (WO-31).

Each adapter is bound to one trusted principal, supplied by the application.
Selectors and payloads carry no authority. Check the required action on every
call before lookup. References require READ and must belong to the same scope.
Missing in-scope revisions raise KeyError, invalid data/pin digests ValueError,
denials PermissionError, and obsolete edits/decisions RevisionConflict.

Payload is a JSON object of scientific fields (e.g. source identity, revision or
access date, content reference, evidence gaps, objective, work type, questions,
limitations). Pins are separate, ordered, exact references. SHA-256 covers the
canonical UTF-8 JSON object {"payload": payload, "references": [asdict(pin), ...]}.
Scope, artifact identity and revision are the other parts of the exact pin.
A read returns a detached snapshot. State is projected from the last receipt for
that exact revision, defaulting to draft. Receipts are returned in append order.

SQLite adapter: SQLiteScientificArtifactRepository(db_path, principal) in
factory.scientific_artifact_repository. Initialize atomically on open using
sci_artifact_ tables and a domain-local migration version. Preserve shared
tables and PRAGMA user_version. Hosted adapters implement this same protocol.
"""

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from .context import digest
from .context_repository import canonical_json

ArtifactKind = Literal["knowledge", "requirement", "blueprint", "specification"]
Decision = Literal["approved", "rejected"]
State = Literal["draft", "approved", "rejected"]

READ = "scientific_artifact.read"
WRITE = "scientific_artifact.write"
DECIDE = "scientific_artifact.decide"


class Principal(Protocol):
    actor_id: str
    is_human: bool

    def require(self, *, lab_id: str, project_id: str | None, action: str) -> None: ...


@dataclass(frozen=True)
class ArtifactPin:
    lab_id: str
    project_id: str
    kind: ArtifactKind
    artifact_id: str
    revision: int
    sha256: str


@dataclass(frozen=True)
class ArtifactRevision:
    pin: ArtifactPin
    predecessor: ArtifactPin | None
    author_id: str
    payload: dict
    references: tuple[ArtifactPin, ...]
    state: State


@dataclass(frozen=True)
class DecisionReceipt:
    specification: ArtifactPin
    decision: Decision
    actor_id: str
    decided_at: str  # UTC ISO 8601
    rationale: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationMarker:
    blueprint: ArtifactPin
    requirement: ArtifactPin
    successor: ArtifactPin  # first newer revision of the pinned requirement


def artifact_digest(payload: dict, references: tuple[ArtifactPin, ...]) -> str:
    body = {"payload": payload, "references": [asdict(pin) for pin in references]}
    return digest(canonical_json(body).encode("utf-8"))


class ScientificArtifactRepository(Protocol):
    def save(self, lab_id: str, project_id: str, kind: ArtifactKind, artifact_id: str,
             payload: dict, *, expected_revision: int,
             references: tuple[ArtifactPin, ...] = ()) -> ArtifactRevision: ...

    def get(self, lab_id: str, project_id: str, kind: ArtifactKind, artifact_id: str,
            *, revision: int | None = None) -> ArtifactRevision: ...

    def history(self, lab_id: str, project_id: str, kind: ArtifactKind,
                artifact_id: str) -> tuple[ArtifactRevision, ...]:
        """Oldest revision first. Unknown artifact raises KeyError."""
        ...

    def decide(self, specification: ArtifactPin, decision: Decision, *, rationale: str,
               limitations: tuple[str, ...] = ()) -> DecisionReceipt: ...

    def decisions(self, specification: ArtifactPin) -> tuple[DecisionReceipt, ...]: ...

    def reconciliation(self, blueprint: ArtifactPin) -> tuple[ReconciliationMarker, ...]:
        """Markers in blueprint reference order, including historical blueprints."""
        ...
