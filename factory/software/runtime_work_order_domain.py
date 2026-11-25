"""Shared transitions for local and hosted runtime work-order stores."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import re

from factory.context import digest
from factory.lab_context.context_repository import canonical_json
from factory.software.runtime_work_order import ACTIONS, Principal, RevisionConflict, RuntimeRecord, RuntimeRecordStore, Scope

_REVIEW_KINDS = {"readiness", "implementation_alignment", "scientific_reasoning", "reproducibility"}
_REVIEW_TERMINAL = {"completed", "failed", "interrupted"}
_TERMINAL = _REVIEW_TERMINAL | {"submitted", "superseded"}
_STATUS_COMMANDS = {"coding_state", "review_state", "submission_validated", "supersede", "interrupt"}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _fields(payload, required, optional=()):
    missing = set(required) - payload.keys()
    extra = payload.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"Missing fields {sorted(missing)} or unexpected fields {sorted(extra)}")


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")


def _strings(value, name):
    _list(value, name)
    for item in value:
        _text(item, name)


def _choice(value, choices, name):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"Invalid {name}, expected one of {sorted(choices)}")


def _sha(value, field):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _pin(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a revision pin with id and sha256")
    _fields(value, ("id", "sha256"))
    _text(value["id"], "pin id")
    _sha(value["sha256"], "pin sha256")


def _validate_task(p):
    _fields(p, ("objective", "scope", "dependencies", "requirements", "blueprints", "specification",
                "acceptance_criteria", "permitted_outputs", "context"), ("output_limits",))
    if "output_limits" in p:
        limits = p["output_limits"]
        if not isinstance(limits, dict):
            raise ValueError("output_limits must be a JSON object")
        _fields(limits, ("max_file_bytes", "max_total_bytes"))
        for name, value in limits.items():
            _integer(value, name)
    for field in ("objective", "scope"):
        _text(p[field], field)
    for field in ("dependencies", "requirements", "blueprints"):
        _list(p[field], field)
        for pin in p[field]:
            _pin(pin)
    _pin(p["specification"])
    for field in ("permitted_outputs", "acceptance_criteria"):
        _strings(p[field], field)
    if not isinstance(p["context"], dict):
        raise ValueError("context must be a JSON object")


def _hash(payload):
    return digest(canonical_json(payload).encode())


def _authority(principal, scope, command):
    # Neither identity nor scope comes from command content. Even replay and
    # unknown-order reads must pass the current grant before touching storage.
    for name, value in asdict(scope).items():
        _text(value, name)
    principal.require(lab_id=scope.lab_id, project_id=scope.project_id, action=ACTIONS[command])
    _text(principal.actor_id, "principal actor_id")
    if command in ("accept", "resolve") and principal.is_human is not True:
        raise PermissionError("A human principal is required")


def _retry(history, principal, command, encoded, key):
    for record in history:
        if record["key"] == key:
            if (record["actor_id"] == principal.actor_id and record["command"] == command
                    and canonical_json(record["payload"]) == encoded):
                return record
            raise RevisionConflict("Idempotency key already used for a different request")
    return None


def _reference(history, version, commands):
    _integer(version, "reference version")
    if version > len(history) or history[version - 1]["command"] not in commands:
        raise RevisionConflict(f"Invalid {commands} reference at version {version}")
    return history[version - 1]


def _attempt_state(history, start):
    """Return the last reported state for exactly this start record."""
    target = start["version"]
    for record in reversed(history[target:]):
        if record["command"] in _STATUS_COMMANDS and record["predecessor"] == target:
            return record["state"]
    return start["state"]


def _candidate(payload, kinds):
    kind, sha = payload["kind"], payload["candidate_sha256"]
    _choice(kind, kinds, "kind")
    if kind == "readiness":
        if sha is not None:
            raise ValueError("Readiness is bound to the task and has no candidate")
    else:
        _sha(sha, "candidate_sha256")
    return sha


def _new_attempt(command, p, history, task):
    if command == "review":
        _fields(p, ("task_version", "kind", "candidate_sha256", "predecessor"), ("model", "prompt_version"))
        candidate = _candidate(p, _REVIEW_KINDS)
        for field in ("model", "prompt_version"):
            if field in p:
                _text(p[field], field)
        state = "queued"
    else:
        _fields(p, ("task_version", "route", "predecessor"))
        _choice(p["route"], {"configured", "external"}, "route")
        state, candidate = "assigned", None

    _integer(p["task_version"], "task_version")
    if p["task_version"] != task["version"]:
        raise RevisionConflict("Superseded task revision")
    predecessor = p["predecessor"]
    if predecessor is not None:
        _integer(predecessor, "predecessor")
    starts = [r for r in history if r["command"] == command and r["task_version"] == task["version"]]
    if command == "claim":
        prior = starts[-1] if starts else None
        if prior and _attempt_state(history, prior) not in _TERMINAL:
            raise RevisionConflict("Task revision already has an active coding assignment")
        if predecessor != (prior["version"] if prior else None):
            raise RevisionConflict("Expected the most recent coding attempt as predecessor")
    elif predecessor is not None:
        prior = _reference(history, predecessor, ("review",))
        if (prior["task_version"] != task["version"] or prior["candidate_sha256"] != candidate
                or prior["payload"]["kind"] != p["kind"]):
            raise RevisionConflict("Review predecessor has different task, context, kind or candidate")
        if _attempt_state(history, prior) not in ("failed", "interrupted"):
            raise RevisionConflict("Review predecessor must be failed or interrupted")
        if any(r["predecessor"] == predecessor for r in starts):
            raise RevisionConflict("Review already has a successor")
    return state, candidate, predecessor


def _target_transition(command, p, history, task, principal):
    if command == "finding":
        _fields(p, ("review", "classification", "rationale", "evidence"))
        _choice(p["classification"], {"blocking", "advisory"}, "classification")
        start = _reference(history, p["review"], ("review",))
    elif command == "resolve":
        _fields(p, ("finding", "rationale", "evidence"))
        start = _reference(history, p["finding"], ("finding",))
        if any(r["command"] == "resolve" and r["predecessor"] == start["version"] for r in history):
            raise RevisionConflict("Finding already has a resolution")
    elif command == "interrupt":
        _fields(p, ("attempt", "evidence"))
        start = _reference(history, p["attempt"], ("review", "claim"))
    elif command in ("submission_validated", "supersede"):
        required = ("attempt", "evidence", "candidate_sha256") if command == "submission_validated" else ("attempt", "evidence")
        _fields(p, required)
        if command == "submission_validated":
            _sha(p["candidate_sha256"], "candidate_sha256")
        start = _reference(history, p["attempt"], ("claim",))
    elif command == "coding_state":
        _fields(p, ("attempt", "state", "evidence"))
        start = _reference(history, p["attempt"], ("claim",))
    else:
        _fields(p, ("review", "state", "evidence"))
        start = _reference(history, p["review"], ("review",))

    _strings(p["evidence"], "evidence")
    if command in ("resolve", "finding"):
        _text(p["rationale"], "rationale")
        if not p["evidence"]:
            raise ValueError("Evidence references are required")
    if command in ("review_state", "finding", "coding_state") and start["actor_id"] != principal.actor_id:
        raise PermissionError("Attempt belongs to another principal")
    if command not in ("resolve", "interrupt", "supersede"):
        if start["task_version"] != task["version"]:
            raise RevisionConflict("Superseded task revision")
    if command == "resolve":
        return start, None

    previous_state = _attempt_state(history, start)
    if previous_state in _TERMINAL:
        raise RevisionConflict("Attempt already reached its terminal state")
    if command == "finding":
        return start, None
    privileged_states = {"interrupt": "interrupted", "submission_validated": "submitted", "supersede": "superseded"}
    if command in privileged_states:
        return start, privileged_states[command]
    state = p["state"]
    if command == "coding_state":
        _choice(state, {"running", "failed", "completion_claim"}, "state")
        if state == "completion_claim":
            return start, previous_state
    else:
        _choice(state, _REVIEW_TERMINAL | {"running"}, "state")
    if state == previous_state:
        raise RevisionConflict("Attempt already has this state")
    return start, state


def _record(scope, principal, history, command, payload, key) -> RuntimeRecord:
    version = len(history) + 1
    task = next((r for r in reversed(history) if r["command"] == "revise"), None)
    state = predecessor = candidate = None
    if command == "revise":
        _validate_task(payload)
        task_version, context_sha, state = version, _hash(payload["context"]), "draft"
        predecessor = task["version"] if task else None
        task_sha = _hash({"scope": asdict(scope), "version": version, "predecessor": predecessor,
                          "payload": payload})
    else:
        if task is None:
            raise RevisionConflict("Create the work order before recording activity")
        target = task
        if command in ("claim", "review"):
            state, candidate, predecessor = _new_attempt(command, payload, history, task)
        elif command == "accept":
            _fields(payload, ("task_version", "kind", "candidate_sha256", "rationale", "evidence"))
            _integer(payload["task_version"], "task_version")
            if payload["task_version"] != task["version"]:
                raise RevisionConflict("Superseded task revision")
            candidate = _candidate(payload, {"readiness", "engineering"})
            _text(payload["rationale"], "rationale")
            _strings(payload["evidence"], "evidence")
        else:
            target, state = _target_transition(command, payload, history, task, principal)
            candidate = payload["candidate_sha256"] if command == "submission_validated" else target["candidate_sha256"]
            predecessor = target["version"]
        task_version, task_sha = target["task_version"], target["task_sha256"]
        context_sha = target["context_sha256"]
    return RuntimeRecord(version=version, command=command, key=key, actor_id=principal.actor_id,
                         created_at=datetime.now(timezone.utc).isoformat(), payload=payload,
                         task_version=task_version, task_sha256=task_sha, context_sha256=context_sha,
                         candidate_sha256=candidate, predecessor=predecessor, state=state)


class RuntimeWorkOrders:
    """Authorizes scoped commands and evaluates them against one consistent history."""
    def __init__(self, store: RuntimeRecordStore):
        self._store = store

    def history(self, principal: Principal, scope: Scope) -> list[RuntimeRecord]:
        _authority(principal, scope, "history")
        return self._store.read(scope)

    def apply(self, principal: Principal, scope: Scope, command: str, payload: dict,
              *, expected_version: int, key: str) -> RuntimeRecord:
        if not isinstance(command, str) or command not in ACTIONS or command == "history":
            raise ValueError("Unknown runtime work-order command")
        _authority(principal, scope, command)
        _integer(expected_version, "expected_version", 0)
        _text(key, "key")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        try:
            encoded = canonical_json(payload)
        except (TypeError, OverflowError) as exc:
            raise ValueError("payload must be JSON serializable") from exc
        history = self._store.read(scope)
        prior = _retry(history, principal, command, encoded, key)
        if prior:
            return prior
        if expected_version != len(history):
            raise RevisionConflict(f"Expected version {expected_version}, current version {len(history)}")
        record = _record(scope, principal, history, command, json.loads(encoded), key)
        try:
            self._store.append(scope, record, expected_version=expected_version)
        except RevisionConflict:
            # Another client may have committed the same request since our read.
            prior = _retry(self._store.read(scope), principal, command, encoded, key)
            if prior:
                return prior
            raise
        return record
