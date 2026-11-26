"""Validate an ordered SOP against a reference manual, entirely in memory."""

from fractions import Fraction
from math import isfinite


# Each family has its own base unit. The scales within a family are exact.
_SCALES = {
    "length": {"pm": 1, "nm": 1000, "um": 10**6, "mm": 10**9,
               "cm": 10**10, "m": 10**12},
    "time": {"ns": 1, "us": 1000, "ms": 10**6, "s": 10**9,
             "min": 60 * 10**9, "h": 3600 * 10**9},
    "frequency": {"Hz": 1, "kHz": 1000, "MHz": 10**6, "GHz": 10**9},
    "voltage": {"uV": 1, "mV": 1000, "V": 10**6},
    "current": {"nA": 1, "uA": 1000, "mA": 10**6, "A": 10**9},
    "power": {"nW": 1, "uW": 1000, "mW": 10**6, "W": 10**9},
    "temperature": {"C": 1, "K": 1, "F": Fraction(5, 9)},
}
_UNITS = {
    unit: (family, scale)
    for family, units in _SCALES.items()
    for unit, scale in units.items()
}
_CELSIUS_ZERO = Fraction("273.15")
_OFFSETS = {"C": _CELSIUS_ZERO, "F": _CELSIUS_ZERO - 32 * Fraction(5, 9)}
_TEMP_ALIASES = {"°C": "C", "degC": "C", "°F": "F", "degF": "F"}


def _number(value):
    if type(value) is int:
        return Fraction(value)
    if type(value) is float and isfinite(value):
        # Use the decimal spelling of the input for inclusive boundary checks.
        return Fraction(str(value))
    raise ValueError("Expected a finite numeric quantity")


def _unit_name(unit):
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("Expected a unit")
    name = unit.strip().replace("µ", "u").replace("μ", "u")
    return _TEMP_ALIASES.get(name, name)


def _convert(value, source, target):
    source, target = _unit_name(source), _unit_name(target)
    if source == target:
        return value
    source_family, source_scale = _UNITS[source]
    target_family, target_scale = _UNITS[target]
    if source_family != target_family:
        raise ValueError("Incompatible units")
    base_value = value * source_scale + _OFFSETS.get(source, 0)
    return (base_value - _OFFSETS.get(target, 0)) / target_scale


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _identifier(value):
    if _text(value) or type(value) is int:
        return value
    raise ValueError("Missing document identifier")


def _limits(spec):
    unit, low, high = spec["unit"], spec["min"], spec["max"]
    if unit is None and low is None and high is None:
        return None, None, None
    _unit_name(unit)
    low, high = _number(low), _number(high)
    if low > high:
        raise ValueError("Inverted manual limits")
    return unit, low, high


def _canonical_value(step, unit, low, high):
    value, source = step["value"], step["unit"]
    if unit is None:
        if value is not None or source is not None:
            raise ValueError("Unexpected command argument")
        return None
    exact = _convert(_number(value), source, unit)
    if not low <= exact <= high:
        raise ValueError("Quantity outside the manual limits")
    if exact.denominator == 1:
        return exact.numerator
    result = float(exact)
    if result == 0:
        raise ValueError("Quantity underflows float representation")
    return result


def solve(request):
    """Return either a complete cited plan or an empty request for input."""
    try:
        if not _text(request["goal"]):
            raise ValueError("Missing goal")
        released, online = request["released"], request["online"]
        if type(released) is not bool or type(online) is not bool:
            raise ValueError("Expected boolean release and online flags")
        sop, manual = request["sop"], request["manual"]
        sop_id, manual_id = _identifier(sop["id"]), _identifier(manual["id"])
        steps, commands = sop["steps"], manual["commands"]
        if not isinstance(steps, list) or not steps or not isinstance(commands, dict):
            raise ValueError("Missing steps or commands")
        limits = {}
        for name, spec in commands.items():
            if not _text(name):
                raise ValueError("Missing command name")
            limits[name] = _limits(spec)
        plan = []
        for step in steps:
            command = step["command"]
            unit, low, high = limits[command]
            plan.append({
                "command": command,
                "value": _canonical_value(step, unit, low, high),
                "unit": unit,
                "citations": [sop_id, manual_id],
            })
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "needs_input", "steps": []}
    return {"status": "simulated" if released and online else "draft", "steps": plan}
