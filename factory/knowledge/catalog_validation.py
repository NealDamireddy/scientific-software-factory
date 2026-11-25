"""Adapter-independent structural checks. Curation assesses scientific eligibility."""
from datetime import date
import json

from jsonschema import Draft202012Validator

from factory.knowledge.catalog_contract import Principal
from factory.lab_context.context_repository import canonical_json

_TEXT = {"type": "string", "pattern": r"\S"}
_TEXTS = {"type": "array", "items": _TEXT}
_DATE = {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}


def _object(fields, *, optional=()):
    return {"type": "object", "properties": fields, "additionalProperties": False,
            "required": [name for name in fields if name not in optional]}


_CITATION = _object({"source_revision_id": _TEXT, "location": _TEXT})
# Claim fields describe validated scientific content. Only citation structure
# and identity are interpreted by the persistence layer.
_CLAIM = {"type": "object", "minProperties": 1,
          "properties": {"citations": {"type": "array", "items": _CITATION}}}
_SOURCE = _object({"title": _TEXT, "reference": _TEXT, "document_revision": _TEXT, "access_date": _DATE},
                  optional=("document_revision", "access_date"))
_SOURCE["anyOf"] = [{"required": ["document_revision"]}, {"required": ["access_date"]}]
_SCHEMAS = {
    "source": _SOURCE,
    "catalog": _object({"model": _TEXT, "claims": {"type": "array", "items": _CLAIM},
                        "unresolved_gaps": {"type": "array"}}),
    "evidence": _object({"model": _TEXT, "tested_configuration": {"type": "object"}, "operation": _TEXT,
                         "adapter_revision": _TEXT, "test_method_revision": _TEXT, "result": _TEXT,
                         "artifact_refs": {**_TEXTS, "minItems": 1}, "test_date": _DATE,
                         "origin": {"enum": ["simulated", "physical"]}, "limitations": _TEXTS}),
}
_VALIDATORS = {kind: Draft202012Validator(schema) for kind, schema in _SCHEMAS.items()}


def authorize(principal: Principal, lab_id: str, action: str) -> None:
    principal.require(lab_id=lab_id, project_id=None, action=action)
    if not isinstance(principal.actor_id, str) or not principal.actor_id.strip():
        raise PermissionError("Missing authenticated actor")


def validate_stream(kind, lab_id, record_id):
    if kind not in _VALIDATORS:
        raise ValueError("kind must be catalog, source or evidence")
    for field, value in (("lab_id", lab_id), ("record_id", record_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a nonempty string")


def validate_revision(value, *, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError(f"revision must be an integer >= {minimum}")


def encode_payload(kind, payload):
    # Validate the same detached snapshot that is digested and committed.
    try:
        encoded = canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be finite JSON") from exc
    snapshot = json.loads(encoded)
    error = next(_VALIDATORS[kind].iter_errors(snapshot), None)
    if error:
        raise ValueError(f"{kind}{error.json_path[1:]}: {error.message}")
    for field in ("access_date", "test_date"):
        if field in snapshot:
            date.fromisoformat(snapshot[field])
    return encoded, snapshot


def cited_source_ids(payload):
    return {citation["source_revision_id"] for claim in payload["claims"]
            for citation in claim.get("citations", [])}
