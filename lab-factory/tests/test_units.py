import pytest

from labfactory.units import UnitError, convert, is_known_unit


@pytest.mark.parametrize(("value", "source", "target", "expected"), [
    (550, "nm", "nm", 550),
    (1000, "uL", "mL", 1),
    (2, "min", "s", 120),
    (25, "degC", "K", 298.15),
    (300, "K", "degC", 26.85),
    (10, "G", "mT", 1),
    (0.5, "T", "mT", 500),
    (0.55, "um", "nm", 550),
    (1, "L", "uL", 1_000_000),
    (1, "h", "ms", 3_600_000),
    (1, "AU", "AU", 1),
])
def test_conversions(value, source, target, expected):
    assert convert(value, source, target) == expected


def test_dimension_mismatch_and_unknown_unit():
    with pytest.raises(UnitError, match="dimension"):
        convert(1, "nm", "mL")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1, "furlong", "nm")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1, "nm", "NM")
    assert is_known_unit("AU") and not is_known_unit("au")


def test_limit_conversion_preserves_decimal_boundaries():
    from fractions import Fraction

    from labfactory.units import convert_exact

    maximum = Fraction("303.15")
    assert convert_exact(30, "degC", "K") == maximum
    assert convert_exact(30.000000000000004, "degC", "K") > maximum
    assert convert_exact(10**400 + 1, "um", "nm") == (10**400 + 1) * 1000
