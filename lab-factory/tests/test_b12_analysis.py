import math

import pytest

from labfactory.b12_analysis import SAMPLE_READINGS, analyze_readings, check_source, validate_readings


ANALYSIS = """def analyze(readings, slope, intercept):
    mean = sum(readings) / len(readings)
    return (mean - intercept) / slope
"""


def test_verifier_runs_source_on_independent_reference_cases():
    checks = check_source(ANALYSIS)
    assert len(checks) >= 5 and all(result.passed for result in checks)
    assert any("intercept" in result.detail for result in checks)
    assert any("mg/L" in result.detail for result in checks)
    indexed = ANALYSIS.replace("sum(readings) / len(readings)",
                               "(readings[0] + readings[1] + readings[2]) / 3")
    assert all(result.passed for result in check_source(indexed))


@pytest.mark.parametrize("formula", [
    "16", "readings[0] / slope", "sum(readings) / 3 / slope", "(sum(readings)/3 - intercept) / 0.0064",
    "1 / 0", "1e300 * 1e300",
])
def test_incorrect_calculations_fail_with_readable_evidence(formula):
    checks = check_source(f"def analyze(readings, slope, intercept):\n    return {formula}")
    assert any(not c.passed and c.detail for c in checks)


@pytest.mark.parametrize("source", [
    "", "def analyze(readings, slope, intercept):\n    return True",
    "def analyze(readings, slope, intercept):\n    return readings[-1]",
    "def analyze(readings, slope, intercept):\n    return sum([1, 2])",
    "def analyze(readings, slope, intercept):\n    return len(readings, extra=1)",
    "def analyze(readings, slope, intercept):\n    readings[0] = 5\n    return 5",
    "def analyze(readings, slope, intercept):\n    return 1\n    return 16",
    "def analyze(readings, slope, intercept):\n    return 2 ** 3",
    "def analyze(readings, slope, intercept):\n    return slope.real",
    "def analyze(readings, slope, intercept):\n    return unknown",
    "def analyze(readings, slope, intercept=0):\n    return 0",
    "def analyze(readings, slope, intercept):\n    import math\n    return 0",
    "@sum\ndef analyze(readings, slope, intercept):\n    return 0",
    "def analyze(readings, slope, intercept):\n    return " + "1+" * 1000 + "1",
    ANALYSIS + "# " + "x" * 4100, ANALYSIS + "# \u202e", ANALYSIS + "# one\r# two",
])
def test_restricted_python_reports_unsupported_source(source):
    assert any(not check.passed for check in check_source(source))


@pytest.mark.parametrize("readings", [None, {}, [0.1], [0.1] * 4, [True, 0.1, 0.1],
                                       ["0.1", 0.1, 0.1], [math.inf, 0.1, 0.1], [math.nan] * 3,
                                       [10 ** 1000, 0.1, 0.1]])
def test_readings_require_exactly_three_finite_json_numbers(readings):
    with pytest.raises(ValueError):
        validate_readings(readings)


@pytest.mark.parametrize(("readings", "expected"), [
    (SAMPLE_READINGS, 16), ([0.0192] * 3, 3), ([0.1536] * 3, 24), ([0.020, 0.030, 0.046], 5),
])
def test_simulated_result_uses_inclusive_frozen_calibration(readings, expected):
    result = analyze_readings(ANALYSIS, readings)
    assert result["status"] == "estimated"
    assert result["concentration_mg_l"] == pytest.approx(expected)
    assert result["mean_absorbance_au"] == pytest.approx(sum(readings) / 3)


@pytest.mark.parametrize("readings", [[0.1, 0.1, 0.16], [-0.01, 0.1, 0.1], [1.79e308] * 3])
def test_any_out_of_range_replicate_withholds_the_concentration(readings):
    result = analyze_readings(ANALYSIS, readings)
    assert result["status"] == "withheld" and result["concentration_mg_l"] is None
    assert "replicate" in result["reason"].lower()
    assert math.isfinite(result["mean_absorbance_au"])


def test_result_from_actual_candidate_must_agree_with_independent_reference():
    wrong = ANALYSIS.replace("return (mean - intercept) / slope", "return 99")
    result = analyze_readings(wrong, [0.08] * 3)
    assert result["status"] == "withheld" and result["concentration_mg_l"] is None
    assert "reference" in result["reason"].lower()


def test_out_of_range_message_shows_the_exact_offending_value():
    above_limit = math.nextafter(0.1536, math.inf)
    result = analyze_readings(ANALYSIS, [0.1, 0.1, above_limit])
    assert result["status"] == "withheld"
    assert repr(above_limit) in result["reason"]
