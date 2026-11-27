"""Compile a selected SOP against an in-memory reference instrument manual."""

from dataclasses import dataclass
from fractions import Fraction
import math


class InvalidEvidence(ValueError):
    pass


def record(value):
    if not isinstance(value, dict):
        raise InvalidEvidence
    return value


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise InvalidEvidence
    return value


def number(value):
    if type(value) is int:
        return Fraction(value)
    if type(value) is float and math.isfinite(value):
        # Use the decimal value supplied through the ordinary-value interface.
        return Fraction(str(value))
    raise InvalidEvidence


@dataclass(frozen=True)
class Unit:
    dimension: str
    scale: Fraction
    offset: Fraction = Fraction(0)


def unit_table():
    units = {}
    prefixes = {
        "q": -30, "r": -27, "y": -24, "z": -21, "a": -18, "f": -15,
        "p": -12, "n": -9, "u": -6, "m": -3, "c": -2, "d": -1,
        "": 0, "da": 1, "h": 2, "k": 3, "M": 6, "G": 9, "T": 12,
        "P": 15, "E": 18, "Z": 21, "Y": 24, "R": 27, "Q": 30,
    }
    for symbol in ("m", "s", "Hz", "V", "A", "W", "Pa", "g", "L"):
        for prefix, exponent in prefixes.items():
            units[prefix + symbol] = Unit(symbol, Fraction(10) ** exponent)
    units["min"] = Unit("s", Fraction(60))
    units["h"] = Unit("s", Fraction(3600))
    units["K"] = Unit("temperature", Fraction(1))
    units["C"] = Unit("temperature", Fraction(1), Fraction("273.15"))
    units["F"] = Unit("temperature", Fraction(5, 9), Fraction("459.67") * Fraction(5, 9))
    for name in ("C", "F"):
        units["°" + name] = units[name]
        units["deg" + name] = units[name]
    return units


UNITS = unit_table()


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    unit: str

    def in_unit(self, target):
        source_name = self.unit.strip().replace("µ", "u").replace("μ", "u")
        target_name = target.strip().replace("µ", "u").replace("μ", "u")
        if source_name == target_name:
            return Quantity(self.value, target)
        source = UNITS.get(source_name)
        dest = UNITS.get(target_name)
        if source is None or dest is None or source.dimension != dest.dimension:
            raise InvalidEvidence
        base = self.value * source.scale + source.offset
        return Quantity((base - dest.offset) / dest.scale, target)

    def output_value(self):
        if self.value.denominator == 1:
            return self.value.numerator
        try:
            value = float(self.value)
        except OverflowError as error:
            raise InvalidEvidence from error
        if not math.isfinite(value) or value == 0:
            raise InvalidEvidence
        return value


@dataclass(frozen=True)
class Limits:
    unit: str
    minimum: Fraction
    maximum: Fraction


@dataclass(frozen=True)
class Command:
    name: str
    limits: Limits | None

    @classmethod
    def from_manual(cls, name, spec):
        label(name)
        spec = record(spec)
        unit, low, high = spec["unit"], spec["min"], spec["max"]
        if unit is None and low is None and high is None:
            return cls(name, None)
        limits = Limits(label(unit), number(low), number(high))
        if limits.minimum > limits.maximum:
            raise InvalidEvidence
        return cls(name, limits)

    def bind(self, value, unit):
        if self.limits is None:
            if value is not None or unit is not None:
                raise InvalidEvidence
            return Step(self, None)
        quantity = Quantity(number(value), label(unit)).in_unit(self.limits.unit)
        if not self.limits.minimum <= quantity.value <= self.limits.maximum:
            raise InvalidEvidence
        return Step(self, quantity)


@dataclass(frozen=True)
class Step:
    command: Command
    quantity: Quantity | None

    def emit(self, sop_id, manual_id):
        return {
            "command": self.command.name,
            "value": self.quantity.output_value() if self.quantity is not None else None,
            "unit": self.quantity.unit if self.quantity is not None else None,
            "citations": [sop_id, manual_id],
        }


def solve(request):
    """Return a complete cited mock plan or abstain on inconsistent evidence."""
    try:
        request = record(request)
        label(request["goal"])
        released, online = request["released"], request["online"]
        if type(released) is not bool or type(online) is not bool:
            raise InvalidEvidence
        sop, manual = record(request["sop"]), record(request["manual"])
        sop_id, manual_id = label(sop["id"]), label(manual["id"])
        commands = {
            name: Command.from_manual(name, spec)
            for name, spec in record(manual["commands"]).items()
        }
        instructions = sop["steps"]
        if not isinstance(instructions, list) or not instructions:
            raise InvalidEvidence
        steps = []
        for instruction in instructions:
            instruction = record(instruction)
            command = commands[label(instruction["command"])]
            steps.append(command.bind(instruction["value"], instruction["unit"]))
        return {
            "status": "simulated" if released and online else "draft",
            "steps": [step.emit(sop_id, manual_id) for step in steps],
        }
    except (InvalidEvidence, KeyError):
        return {"status": "needs_input", "steps": []}
