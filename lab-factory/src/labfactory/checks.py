"""Deterministic checks of a candidate against its pinned context."""

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
import re

from .artifacts import AnalysisApp, Procedure, ProcedureStep, RunPlan, Setting, format_citation, format_number
from .context import Command, Experiment, Instrument, Lab
from .units import UNIT_SPELLINGS, UnitError, convert_exact, is_known_unit


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def all_passed(results: list[CheckResult]) -> bool:
    return bool(results) and all(result.passed for result in results)


_SYMBOLS = (*UNIT_SPELLINGS, "°C", "µL", "μL", "µm", "μm")
_SYMBOL_PATTERN = "|".join(re.escape(token) for token in sorted(_SYMBOLS, key=len, reverse=True))
_WORD_PATTERN = (
    r"nanometers?|micrometers?|microliters?|milliliters?|liters?|milliseconds?|"
    r"seconds?|sec|minutes?|mins|hours?|hrs?|kelvin|celsius|gauss|tesla|millitesla"
)
_QUANTITY = re.compile(rf"(?<!\d)\d+(?:\.\d+)?\s*(?:(?ai:{_WORD_PATTERN})|{_SYMBOL_PATTERN})")


def find_text_quantities(text: str) -> list[str]:
    return [
        match.group()
        for match in _QUANTITY.finditer(text)
        if not text[match.end():match.end() + 1].isalpha()
    ]


def _instrument_check(lab: Lab, experiment: Experiment, instrument_id: str, name: str):
    instrument = lab.instrument(instrument_id) if instrument_id in experiment.instrument_ids else None
    if instrument is None:
        return None, CheckResult(name, False, f"unknown instrument {instrument_id} in the pinned lab or experiment")
    return instrument, CheckResult(name, True, f"{instrument_id} is listed")


def _setting_error(
    setting: Setting,
    instrument: Instrument | None,
    instrument_id: str,
    command: Command | None,
    command_name: str,
    repeated: bool,
) -> str | None:
    if instrument is None:
        return f"unknown instrument {instrument_id}"
    parameter = instrument.parameter(setting.parameter)
    if parameter is None:
        return f"unknown parameter {setting.parameter}"
    if command is None:
        return f"unknown command {command_name} on {instrument_id}"
    if setting.parameter not in command.required and setting.parameter not in command.optional:
        return f"{setting.parameter} not accepted by {command.name}"
    if repeated:
        return f"duplicate setting {setting.parameter}"
    try:
        value = convert_exact(setting.value, setting.unit, parameter.unit)
    except UnitError as error:
        return str(error)
    if not Fraction(str(parameter.minimum)) <= value <= Fraction(str(parameter.maximum)):
        return (
            f"{format_number(setting.value)} {setting.unit} is outside "
            f"[{format_number(parameter.minimum)}, {format_number(parameter.maximum)}] {parameter.unit}"
        )
    return None


def _command_checks(
    prefix: str, instrument_id: str, instrument: Instrument | None,
    command_name: str, settings: tuple[Setting, ...],
) -> list[CheckResult]:
    counts = Counter(setting.parameter for setting in settings)
    command = instrument.command(command_name) if instrument is not None else None
    if instrument is None:
        problems = [f"unknown instrument {instrument_id}"]
    elif command is None:
        problems = [f"unknown command {command_name} on {instrument_id}"]
    else:
        problems = [f"missing required setting {p}" for p in command.required if p not in counts]
        problems.extend(f"duplicate setting {p}" for p, n in counts.items() if n > 1)
    detail = "; ".join(problems) if problems else f"{command_name} has all required settings"
    results = [CheckResult(prefix + "command", not problems, detail)]
    for setting in settings:
        error = _setting_error(
            setting, instrument, instrument_id, command, command_name, counts[setting.parameter] > 1
        )
        detail = error or f"{format_number(setting.value)} {setting.unit} is within limits"
        results.append(CheckResult(prefix + setting.parameter, error is None, detail))
    return results


def _procedure_checks(prefix: str, step: ProcedureStep, document_counts: Counter[str]) -> list[CheckResult]:
    citation_errors = []
    for document_id in step.citations:
        count = document_counts[document_id]
        if count == 0:
            citation_errors.append(f"unknown document {format_citation(document_id)}")
        elif count > 1:
            citation_errors.append(f"ambiguous document {format_citation(document_id)} in pinned context")
    if not step.citations:
        citation_errors.append("no citation")
    citation_detail = ", ".join(citation_errors or map(format_citation, step.citations))
    matches = find_text_quantities(step.text)
    text_detail = "no matching numeric unit expressions"
    if matches:
        text_detail = (
            f"{', '.join(matches)}: put instrument values in the action "
            "and hand-measured values in amounts"
        )
    results = [
        CheckResult(prefix + "citations", not citation_errors, citation_detail),
        CheckResult(prefix + "text values", not matches, text_detail),
    ]
    for amount in step.amounts:
        known = is_known_unit(amount.unit)
        detail = f"known unit {amount.unit}" if known else f"unknown unit {amount.unit}"
        results.append(CheckResult(prefix + f"amount {amount.what}", known, detail))
    return results


def check_artifact(artifact: RunPlan | Procedure | AnalysisApp, lab: Lab, experiment: Experiment) -> list[CheckResult]:
    if isinstance(artifact, AnalysisApp):
        from .b12_analysis import check_source
        from .b12_service import calibration_checks

        return [*calibration_checks(lab, experiment), *check_source(artifact.source)]
    if isinstance(artifact, RunPlan):
        instrument, listed = _instrument_check(lab, experiment, artifact.instrument_id, "instrument listed")
        results = [listed]
        for index, step in enumerate(artifact.steps, start=1):
            results.extend(_command_checks(
                f"step {index}: ", artifact.instrument_id, instrument, step.command, step.settings
            ))
        return results

    document_counts = Counter(document.id for document in (*lab.documents, *experiment.documents))
    results = []
    for index, step in enumerate(artifact.steps, start=1):
        prefix = f"step {index}: "
        results.extend(_procedure_checks(prefix, step, document_counts))
        action = step.action
        if action is not None:
            instrument, listed = _instrument_check(lab, experiment, action.instrument_id, prefix + "instrument listed")
            results.append(listed)
            results.extend(_command_checks(prefix, action.instrument_id, instrument, action.command, action.settings))
    return results
