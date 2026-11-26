"""Case-sensitive units and conversions for instrument settings."""

from fractions import Fraction


class UnitError(ValueError):
    """An unknown unit or incompatible conversion."""


# Canonical value = supplied value * scale + offset.
_UNITS = {
    "nm": ("length", 1, 0),
    "um": ("length", 1000, 0),
    "mL": ("volume", 1, 0),
    "uL": ("volume", Fraction(1, 1000), 0),
    "L": ("volume", 1000, 0),
    "s": ("time", 1, 0),
    "ms": ("time", Fraction(1, 1000), 0),
    "min": ("time", 60, 0),
    "h": ("time", 3600, 0),
    "K": ("temperature", 1, 0),
    "degC": ("temperature", 1, Fraction("273.15")),
    "mT": ("field", 1, 0),
    "G": ("field", Fraction(1, 10), 0),
    "T": ("field", 1000, 0),
    "AU": ("absorbance", 1, 0),
}
UNIT_SPELLINGS = tuple(_UNITS)


def is_known_unit(unit: str) -> bool:
    return unit in _UNITS


def convert_exact(value: float, from_unit: str, to_unit: str) -> Fraction:
    """Convert the JSON number's decimal spelling, for inclusive limit checks."""
    try:
        dimension, scale, offset = _UNITS[from_unit]
        target_dimension, target_scale, target_offset = _UNITS[to_unit]
    except KeyError as error:
        raise UnitError(f"unknown unit {error.args[0]}") from error
    if dimension != target_dimension:
        raise UnitError(f"dimension mismatch: {from_unit} ({dimension}) to "
                        f"{to_unit} ({target_dimension})")
    canonical = Fraction(str(value)) * scale + offset
    return (canonical - target_offset) / target_scale


def convert(value: float, from_unit: str, to_unit: str) -> float:
    return float(convert_exact(value, from_unit, to_unit))
