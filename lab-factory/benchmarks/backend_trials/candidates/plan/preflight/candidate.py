"""Dry-run an ordered procedure against a request-local reference instrument."""

from fractions import Fraction
from math import isfinite

try:
    from labfactory.units import convert_exact
except ModuleNotFoundError as error:
    if error.name != "labfactory":
        raise
    # Benchmarks can also import this single file from an uninstalled checkout.
    from pathlib import Path
    from runpy import run_path

    units_path = Path(__file__).resolve().parents[5] / "src/labfactory/units.py"
    convert_exact = run_path(str(units_path))["convert_exact"]


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonempty text")
    return value


def _record(value):
    if not isinstance(value, dict):
        raise ValueError("expected record")
    return value


def _number(value):
    if type(value) is int:
        return Fraction(value)
    if type(value) is float and isfinite(value):
        return Fraction(str(value))
    raise ValueError("expected finite number")


def _ordinary_number(exact):
    if exact.denominator == 1:
        return exact.numerator
    value = float(exact)
    if value == 0 or not isfinite(value):
        raise ValueError("unrepresentable result")
    return value


_ALIASES = {"C": "degC", "°C": "degC", "µm": "um", "μm": "um",
            "µL": "uL", "μL": "uL"}


class _ReferenceInstrument:
    def __init__(self, commands):
        self.commands = {}
        self.settings = {}
        for name, spec in _record(commands).items():
            _text(name)
            _record(spec)
            unit, low, high = spec["unit"], spec["min"], spec["max"]
            if unit is None:
                if low is not None or high is not None:
                    raise ValueError("bounds on a parameterless command")
            else:
                _text(unit)
                low, high = _number(low), _number(high)
                if low > high:
                    raise ValueError("reversed manual limits")
            self.commands[name] = (unit, low, high)

    def prepare(self, step):
        _record(step)
        name = _text(step["command"])
        target, _, _ = self.commands[name]
        value, source = step["value"], step["unit"]
        if target is None:
            if value is not None or source is not None:
                raise ValueError("unexpected argument")
            return name, None, None
        _text(source)
        exact = _number(value)
        source_key = _ALIASES.get(source, source)
        target_key = _ALIASES.get(target, target)
        if source_key != target_key:
            exact = convert_exact(value, source_key, target_key)
        return name, exact, target

    def execute(self, instruction, citations):
        name, exact, unit = instruction
        if exact is None:
            readback = None
        else:
            _, low, high = self.commands[name]
            if not low <= exact <= high:
                raise ValueError("setpoint outside manual limits")
            self.settings[name] = exact
            readback = _ordinary_number(self.settings[name])
        return {"command": name, "value": readback, "unit": unit,
                "citations": list(citations)}


def solve(request):
    try:
        _record(request)
        _text(request["goal"])
        sop = _record(request["sop"])
        manual = _record(request["manual"])
        citations = (_text(sop["id"]), _text(manual["id"]))
        released, online = request["released"], request["online"]
        if type(released) is not bool or type(online) is not bool:
            raise ValueError("missing release or connectivity evidence")
        steps = sop["steps"]
        if not isinstance(steps, list) or not steps:
            raise ValueError("empty or malformed procedure")

        instrument = _ReferenceInstrument(manual["commands"])
        planned = [instrument.prepare(step) for step in steps]
        receipts = [instrument.execute(step, citations) for step in planned]
        return {"status": "simulated" if released and online else "draft",
                "steps": receipts}
    except (KeyError, ValueError, OverflowError):
        return {"status": "needs_input", "steps": []}
