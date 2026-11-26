"""Immutable lab and experiment records and their canonical JSON representation."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .units import is_known_unit


class ContextError(ValueError):
    """A context record cannot be used as supplied."""


@dataclass(frozen=True)
class Parameter:
    name: str
    unit: str
    minimum: float
    maximum: float


@dataclass(frozen=True)
class Command:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    model: str
    firmware: str
    parameters: tuple[Parameter, ...]
    commands: tuple[Command, ...]
    notes: str = ""

    def parameter(self, name: str) -> Parameter | None:
        return next((p for p in self.parameters if p.name == name), None)

    def command(self, name: str) -> Command | None:
        return next((c for c in self.commands if c.name == name), None)


@dataclass(frozen=True)
class Document:
    id: str
    kind: str
    title: str
    source: str
    text: str


@dataclass(frozen=True)
class Lab:
    id: str
    name: str
    instruments: tuple[Instrument, ...]
    documents: tuple[Document, ...]

    def instrument(self, id: str) -> Instrument | None:
        return next((i for i in self.instruments if i.id == id), None)

    def document(self, id: str) -> Document | None:
        return next((d for d in self.documents if d.id == id), None)


@dataclass(frozen=True)
class Experiment:
    id: str
    lab_id: str
    title: str
    goal: str
    instrument_ids: tuple[str, ...]
    documents: tuple[Document, ...]


def _object(value, kind, required, optional=()):
    if not isinstance(value, dict):
        raise ContextError(f"{kind} must be an object")
    for key in required:
        if key not in value:
            raise ContextError(f"{kind} is missing {key}")
    for key in value:
        if key not in required and key not in optional:
            raise ContextError(f"unknown {kind} field {key}")


def _string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ContextError(f"{field} must be a nonempty string")
    return value


def _identifier(value, field):
    _string(value, field)
    if not value.isprintable():
        raise ContextError(f"{field} must be printable")
    return value


def _number(value, field):
    if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
        raise ContextError(f"{field} must be a finite number")
    return value


def _unique(values, field):
    seen = set()
    for value in values:
        if value in seen:
            raise ContextError(f"duplicate {field}: {value}")
        seen.add(value)


def _items(d, field, parse, *, default=None):
    values = d.get(field, default)
    if not isinstance(values, list):
        raise ContextError(f"{field} must be a list")
    return tuple(parse(item) for item in values)


def _strings(d, keys):
    return {k: _identifier(d[k], k) if k in ("id", "lab_id") else _string(d[k], k) for k in keys}


def _parameter(d):
    _object(d, "parameter", ("name", "unit", "minimum", "maximum"))
    name = _identifier(d["name"], "parameter name")
    unit = _string(d["unit"], "parameter unit")
    if not is_known_unit(unit):
        raise ContextError(f"unknown unit {unit} on {name}")
    low = _number(d["minimum"], "minimum")
    high = _number(d["maximum"], "maximum")
    if low > high:
        raise ContextError(f"{name}: minimum exceeds maximum")
    return Parameter(name, unit, low, high)


def _command(d):
    _object(d, "command", ("name", "required"), ("optional",))
    name = _identifier(d["name"], "command name")
    required = _items(d, "required", lambda v: _identifier(v, "required parameter"))
    optional = _items(d, "optional", lambda v: _identifier(v, "optional parameter"), default=[])
    _unique((*required, *optional), f"command parameter on {name}")
    return Command(name, required, optional)


def _instrument(d):
    labels = ("id", "name", "model", "firmware")
    _object(d, "instrument", (*labels, "parameters", "commands"), ("notes",))
    parameters = _items(d, "parameters", _parameter)
    commands = _items(d, "commands", _command)
    names = {p.name for p in parameters}
    _unique((p.name for p in parameters), "parameter name")
    _unique((c.name for c in commands), "command name")
    for command in commands:
        for name in (*command.required, *command.optional):
            if name not in names:
                raise ContextError(f"{command.name}: unknown parameter {name}")
    notes = d.get("notes", "")
    if not isinstance(notes, str):
        raise ContextError("instrument notes must be a string")
    return Instrument(**_strings(d, labels), parameters=parameters, commands=commands, notes=notes)


def _document(d):
    fields = ("id", "kind", "title", "source", "text")
    _object(d, "document", fields)
    doc = Document(**_strings(d, fields))
    if doc.kind not in ("sop", "manual", "standard", "paper", "note"):
        raise ContextError(f"unknown document kind {doc.kind}")
    return doc


def _documents(d):
    documents = _items(d, "documents", _document)
    _unique((doc.id for doc in documents), "document id")
    return documents


def lab_from_dict(d: dict) -> Lab:
    _object(d, "lab", ("id", "name", "instruments", "documents"))
    instruments = _items(d, "instruments", _instrument)
    _unique((i.id for i in instruments), "instrument id")
    return Lab(**_strings(d, ("id", "name")), instruments=instruments, documents=_documents(d))


def experiment_from_dict(d: dict, *, allow_unassigned: bool = False) -> Experiment:
    fields = ("id", "lab_id", "title", "goal")
    _object(d, "experiment", (*fields, "instrument_ids", "documents"))
    ids = _items(d, "instrument_ids", lambda v: _identifier(v, "instrument id"))
    if not ids and not allow_unassigned:
        raise ContextError("instrument_ids must contain at least one instrument")
    _unique(ids, "instrument id")
    return Experiment(**_strings(d, fields), instrument_ids=ids, documents=_documents(d))


def to_dict(record) -> dict:
    # Dataclasses hold immutable tuples. JSON clients receive arrays.
    return json.loads(json.dumps(asdict(record), allow_nan=False))


def canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(data: dict) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def digest(record) -> str:
    return canonical_digest(to_dict(record))


def unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ContextError(f"duplicate JSON field {key!r}")
        fields[key] = value
    return fields
