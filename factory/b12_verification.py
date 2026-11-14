"""Integrity checks for B12 receipts written by the trusted local verifier."""
from .b12_build import content_revision
from .context import digest
from .uvvis_contract import canonical


UNBOUND_VERIFICATION = "Historical release lacks revision-bound verification; generate a fresh verified release"


def verification_receipt(revision, checks, worker, contract):
    """Bind the host's recorded evidence and provenance to its verified source.

    The content digest detects stale evidence. Like the local release repository,
    this assumes the verifier's records are trusted; it is not a signature.
    """
    evidence = {"source_revision": revision, "checks": checks, "worker": worker, "contract": contract}
    return {
        "schema": "b12-verification@1",
        "source_revision": revision,
        "evidence_sha256": digest(canonical(evidence).encode("utf-8")),
    }


def validate_receipt(task, files, contract):
    """Validate the exact byte snapshot selected for reuse, without altering legacy records."""
    revision = content_revision(files)
    if revision != task["revision"]:
        raise ValueError("Released source digest mismatch")
    if "verification" not in task:
        raise ValueError(UNBOUND_VERIFICATION)
    expected = verification_receipt(revision, task["checks"], task["worker"], contract)
    if task["verification"] != expected:
        raise ValueError("Revision-bound verification evidence mismatch")
    return expected
