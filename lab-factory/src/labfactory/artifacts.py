"""Candidate artifact formats and the instructions shown to a reviewer."""

from collections.abc import Callable
from dataclasses import dataclass
import json
from math import isfinite
import re
from typing import TypeVar

from .b12_analysis import MAX_SOURCE_CHARS


class ArtifactError(ValueError):
    """The submitted JSON does not have the shape of its work-order kind."""


KINDS = ("procedure", "run_plan", "analysis_app")


@dataclass(frozen=True)
class AnalysisApp:
    source: str


@dataclass(frozen=True)
class Setting:
    parameter: str
    value: float
    unit: str


@dataclass(frozen=True)
class RunStep:
    command: str
    settings: tuple[Setting, ...]


@dataclass(frozen=True)
class RunPlan:
    instrument_id: str
    steps: tuple[RunStep, ...]


@dataclass(frozen=True)
class Action:
    instrument_id: str
    command: str
    settings: tuple[Setting, ...]


@dataclass(frozen=True)
class Amount:
    what: str
    value: float
    unit: str


@dataclass(frozen=True)
class ProcedureStep:
    text: str
    citations: tuple[str, ...]
    action: Action | None = None
    amounts: tuple[Amount, ...] = ()


@dataclass(frozen=True)
class Procedure:
    steps: tuple[ProcedureStep, ...]


def _fields(value: object, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(value, dict):
        raise ArtifactError("expected a JSON object")
    for key in required:
        if key not in value:
            raise ArtifactError(f"missing {key}")
    for key in value:
        if key not in required and key not in optional:
            raise ArtifactError(f"unknown field {key!r}")
    return value


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or not value.isprintable():
        raise ArtifactError(f"{name} must be a non-empty, printable string")
    return value


def _number(value: object) -> float:
    if type(value) not in (int, float) or (isinstance(value, float) and not isfinite(value)):
        raise ArtifactError("value must be a finite JSON number")
    return value


T = TypeVar("T")


def _items(value: object, name: str, parse: Callable[[object], T]) -> tuple[T, ...]:
    if not isinstance(value, list):
        raise ArtifactError(f"{name} must be a JSON array")
    items = []
    for index, item in enumerate(value, start=1):
        try:
            items.append(parse(item))
        except ArtifactError as error:
            raise ArtifactError(f"{name} item {index}: {error}") from error
    return tuple(items)


def _setting(value: object) -> Setting:
    data = _fields(value, ("parameter", "value", "unit"))
    return Setting(_label(data["parameter"], "parameter"), _number(data["value"]), _label(data["unit"], "unit"))


def _amount(value: object) -> Amount:
    data = _fields(value, ("what", "value", "unit"))
    return Amount(_label(data["what"], "what"), _number(data["value"]), _label(data["unit"], "unit"))


def _run_step(value: object) -> RunStep:
    data = _fields(value, ("command", "settings"))
    return RunStep(_label(data["command"], "command"), _items(data["settings"], "settings", _setting))


def _action(value: object) -> Action:
    data = _fields(value, ("instrument_id", "command", "settings"))
    return Action(
        _label(data["instrument_id"], "instrument_id"),
        _label(data["command"], "command"),
        _items(data["settings"], "settings", _setting),
    )


def _procedure_step(value: object) -> ProcedureStep:
    data = _fields(value, ("text",), ("citations", "action", "amounts"))
    if not isinstance(data["text"], str):
        raise ArtifactError("text must be a string")
    return ProcedureStep(
        text=data["text"],
        citations=_items(data.get("citations", []), "citations", lambda c: _label(c, "citation")),
        action=_action(data["action"]) if data.get("action") is not None else None,
        amounts=_items(data.get("amounts", []), "amounts", _amount),
    )


def parse_artifact(kind: str, data: dict) -> RunPlan | Procedure | AnalysisApp:
    if kind not in KINDS:
        raise ArtifactError(f"unknown artifact kind {kind!r}")
    if kind == "analysis_app":
        source = _fields(data, ("source",))["source"]
        if not isinstance(source, str) or not source.strip():
            raise ArtifactError("source must contain the analysis function")
        # Limit the exact text both here and at the evaluator entry point.
        display_text = source.replace("\r\n", "\n")
        if len(source) > MAX_SOURCE_CHARS or not all(c.isprintable() or c in "\n\t" for c in display_text):
            raise ArtifactError(f"source must be printable Python of at most {MAX_SOURCE_CHARS} characters")
        return AnalysisApp(source)
    fields = ("steps", "instrument_id") if kind == "run_plan" else ("steps",)
    data = _fields(data, fields)
    if data["steps"] == []:
        raise ArtifactError("steps must contain at least one step")
    if kind == "run_plan":
        return RunPlan(
            _label(data["instrument_id"], "instrument_id"),
            _items(data["steps"], "steps", _run_step),
        )
    return Procedure(_items(data["steps"], "steps", _procedure_step))


def format_number(value: float) -> str:
    """Retain Python's round-trip spelling and omit an integral float's trailing .0."""
    return str(value).removesuffix(".0")


def format_citation(document_id: str) -> str:
    """Keep simple IDs readable and quote IDs whose punctuation could be misread."""
    if re.fullmatch(r"[\w.-]+", document_id):
        return document_id
    return json.dumps(document_id, ensure_ascii=False)


def _render_command(instrument_id: str, command: str, settings: tuple[Setting, ...]) -> str:
    values = ", ".join(f"{s.parameter} {format_number(s.value)} {s.unit}" for s in settings)
    return f"On {instrument_id}: {command} ({values})"


def render_step(step: ProcedureStep) -> list[str]:
    lines = []
    if step.action is not None:
        lines.append(_render_command(step.action.instrument_id, step.action.command, step.action.settings))
    if step.amounts:
        amounts = ", ".join(f"{a.what} {format_number(a.value)} {a.unit}" for a in step.amounts)
        lines.append(f"Amounts, not checked against instrument limits: {amounts}")
    if step.text:
        # Keep even multiline notes inside their labeled line on a reviewer's terminal.
        notes = step.text if step.text.isprintable() else repr(step.text)
        lines.append(f"Notes, not checked by code: {notes}")
    if step.citations:
        lines.append("Citations: " + ", ".join(map(format_citation, step.citations)))
    return lines


def render_procedure(procedure: Procedure) -> str:
    sections = []
    for index, step in enumerate(procedure.steps, start=1):
        lines = [f"Step {index}", *(f"  {line}" for line in render_step(step))]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def render_run_plan(plan: RunPlan) -> str:
    sections = []
    for index, step in enumerate(plan.steps, start=1):
        action = _render_command(plan.instrument_id, step.command, step.settings)
        sections.append(f"Step {index}\n  {action}")
    return "\n\n".join(sections)


def render_artifact(kind: str, data: dict, *, experiment_id: str | None = None) -> str:
    if kind == "analysis_app":
        from .honey_service import EXPERIMENT_ID

        if experiment_id == EXPERIMENT_ID:
            # Failed submissions also need an exact, printable representation for review.
            return json.dumps(data, ensure_ascii=True, indent=2)
    artifact = parse_artifact(kind, data)
    if isinstance(artifact, AnalysisApp):
        return artifact.source
    if isinstance(artifact, Procedure):
        return render_procedure(artifact)
    return render_run_plan(artifact)


ARTIFACT_EXAMPLES: dict[str, dict] = {
    # A signature for the worker. The factory verifies the worker's actual implementation.
    "analysis_app": {"source": "def analyze(readings, slope, intercept):\n    # Implement the pinned calibration.\n    pass\n"},
    "run_plan": {
        "instrument_id": "uvvis-1",
        "steps": [{
            "command": "read_absorbance",
            "settings": [{"parameter": "wavelength", "value": 550, "unit": "nm"}],
        }],
    },
    "procedure": {
        "steps": [
            {"text": "Rinse the cuvette twice with buffer.", "citations": ["sop-cuvette"]},
            {
                "text": "Pipette the sample into the cuvette.",
                "citations": ["b12-protocol"],
                "amounts": [{"what": "sample", "value": 1, "unit": "mL"}],
            },
            {
                "text": "Place the cuvette in the holder and read the absorbance.",
                "citations": ["sop-cuvette"],
                "action": {
                    "instrument_id": "uvvis-1",
                    "command": "read_absorbance",
                    "settings": [{"parameter": "wavelength", "value": 550, "unit": "nm"}],
                },
            },
        ],
    },
}
