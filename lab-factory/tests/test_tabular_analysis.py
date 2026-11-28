from copy import deepcopy
import math

import pytest

from labfactory.checks import all_passed
from labfactory.tabular_analysis import check, evaluate, verify_control


CALIBRATED = """def analyze(standards, signal, factor):
    areas = column(standards, 0)
    concentrations = column(standards, 1)
    gradient = slope(concentrations, areas)
    background = intercept(concentrations, areas)
    return (signal - background) / gradient * factor
"""

OPTICAL_DENSITY = """def analyze(standards, signal, factor):
    return -log10(signal / 100) * factor
"""


def example(source=CALIBRATED):
    return {
        "source": source,
        "explanation": "Fit signal as a function of known concentration. Invert the fit and apply dilution.",
        "tests": [
            {"label": "Nonzero blank", "standards": [[3, 0], [13, 5], [23, 10]], "signal": 11,
             "factor": 1, "expected": 4},
            {"label": "Diluted sample", "standards": [[1, 0], [4, 1], [7, 2]], "signal": 7,
             "factor": 3, "expected": 6},
        ],
    }


def test_generic_forward_fit_runs_the_submitted_method_against_changed_batch():
    candidate = example()
    assert all_passed(check(candidate))
    assert evaluate(candidate, [[7, 0], [27, 10], [47, 20]], 22, 4) == pytest.approx(30)
    assert evaluate(candidate, [[2, 0], [12, 2.5], [22, 5]], 22, 4) == pytest.approx(20)
    # Protocol fits response on known concentration. Uneven residuals distinguish
    # inverse OLS from calibration followed by algebraic inversion.
    assert evaluate(candidate, [[2, 0], [9, 1], [9, 2]], 9) == pytest.approx(5 / 3)
    assert verify_control(candidate, [[7, 0], [27, 10], [47, 20]], 22, 1, 7.5, 0.2) == {
        "passed": True, "predicted": 7.5, "expected": 7.5, "error": 0.0, "tolerance": 0.2, "reason": "",
    }


def test_bad_candidate_passes_its_own_tests_but_fails_the_same_blind_path():
    candidate = example("def analyze(standards, signal, factor):\n    return signal * factor\n")
    for case in candidate["tests"]:
        case["expected"] = case["signal"] * case["factor"]
    assert all_passed(check(candidate))
    report = verify_control(candidate, [[7, 0], [27, 10], [47, 20]], 22, 1, 7.5, 0.2)
    assert not report["passed"] and report["predicted"] == 22 and report["error"] == 14.5


def test_different_experiment_uses_same_contract_and_execution():
    candidate = {
        "explanation": "Calculate optical density from transmittance in percent.",
        "source": OPTICAL_DENSITY,
        "tests": [
            {"label": "Clear", "standards": [], "signal": 100, "factor": 1, "expected": 0.0},
            {"label": "One percent", "standards": [], "signal": 1, "factor": 1, "expected": 2.0},
        ],
    }
    assert all_passed(check(candidate))
    assert evaluate(candidate, [], 50, range_gate=False) == pytest.approx(math.log10(2))
    assert verify_control(candidate, [], 10, 1, 1, 0.003, range_gate=False)["passed"]


@pytest.mark.parametrize("signal", [-1, 1e5])
def test_calibration_range_withholds_control_and_unknown(signal):
    candidate = example()
    standards = [[0, 0], [2, 1]]
    with pytest.raises(ValueError, match="range"):
        evaluate(candidate, standards, signal)
    result = verify_control(candidate, standards, signal, 1, 1, 0.1)
    assert result["predicted"] is None and not result["passed"] and "range" in result["reason"]


def test_tolerance_is_inclusive_and_absolute():
    candidate = example("def analyze(standards, signal, factor):\n    return signal\n")
    args = (candidate, [[1, 0], [2, 9]], 1.2, 1, 1.1)
    assert verify_control(*args, 0.1)["passed"]
    assert not verify_control(*args, 0.099)["passed"]
    with pytest.raises(ValueError):
        verify_control(*args, -1)


def test_interpolation_handles_knots_and_wide_finite_intervals():
    candidate = example("def analyze(standards, signal, factor):\n    return interpolate(standards, signal)")
    table = [[8, 0], [4, 3], [6, -1]]
    for signal, expected in [(4, 3), (5, 1), (6, -1), (7, -0.5), (8, 0)]:
        assert evaluate(candidate, table, signal) == expected
    assert evaluate(candidate, [[-1e308, 1e308], [1e308, -1e308]], 0) == 0


@pytest.mark.parametrize(("table", "signal", "reason"), [
    ([], 0, "two standards"), ([[0, 1]], 0, "two standards"),
    ([[1, 2], [2, 3], [2, 4]], 1, "unique signals"),
    ([[1, 2], [2, 3]], 0, "range"), ([[1, 2], [2, 3]], 3, "range"),
])
def test_invalid_interpolation_withholds_control_even_without_range_gate(table, signal, reason):
    candidate = example("def analyze(standards, signal, factor):\n    return interpolate(standards, signal)")
    report = verify_control(candidate, table, signal, 1, 0, 1, range_gate=False)
    assert not report["passed"] and report["predicted"] is None and reason in report["reason"]


def test_preexisting_local_named_interpolate_still_runs():
    candidate = example("def analyze(standards, signal, factor):\n    interpolate = signal / factor\n    return interpolate")
    assert evaluate(candidate, [], 6, 2, range_gate=False) == 3


def test_matlab_table_and_scalar_calculation():
    candidate = example("function result = analyze(standards, signal, factor)\n"
                        "result = (interp1(standards(:,1), standards(:,2), signal, 'linear') + 1) / sqrt(factor);\nend")
    candidate["language"] = "matlab"
    assert evaluate(candidate, [[3, 9], [1, 1], [2, 3]], 2.5, 4) == 3.5
    assert not verify_control(candidate, [[3, 9], [1, 1]], 4, 1, 0, 1, range_gate=False)["passed"]


@pytest.mark.parametrize("statement", [
    "result = mean(standards);", "result = signal; result = factor;",
    "if signal > 0\nresult = 1;\nend", "result = signal ** 2;",
    "result = interp1(standards(:,2), standards(:,1), signal);",
    "result = signal; % a comment\rresult = factor;",
])
def test_unsupported_matlab_source_fails_public_checks(statement):
    candidate = example("function result = analyze(standards, signal, factor)\n" + statement + "\nend")
    candidate["language"] = "matlab"
    result, = check(candidate)
    assert result.name == "Submitted numerical analysis" and not result.passed


@pytest.mark.parametrize("source", [
    "import math\ndef analyze(standards, signal, factor):\n    return signal",
    "def analyze(standards, signal, factor):\n    return expected",
    "def analyze(standards, signal, factor):\n    return 'unknown'",
    "def analyze(standards, signal, factor):\n    return [signal]",
    "def analyze(standards, signal, factor):\n    return signal ** 65",
    "def analyze(standards, signal, factor):\n    return standards[-1][0]",
    "def analyze(standards, signal, factor):\n    return signal / 0",
    "def analyze(standards, signal, factor):\n    return 1e300 * 1e300",
    "def analyze(standards, signal, factor):\n    signal = 0\n    return signal",
])
def test_unavailable_data_and_invalid_calculations_get_readable_errors(source):
    candidate = example(source)
    with pytest.raises(ValueError):
        evaluate(candidate, [[7, 0], [10, 10]], 8)
    assert not all_passed(check(candidate))


def test_invalid_numerical_data_and_authored_tests():
    candidate = example()
    case = candidate["tests"][0]
    for readings, signal, factor in [([["3", 0]], 3, 1), ([[True, 0]], 1, 1),
                                     (case["standards"], 13, float("inf")), (case["standards"], 13, 0)]:
        with pytest.raises(ValueError):
            evaluate(candidate, readings, signal, factor)
    candidate["tests"] = [case, deepcopy(case)]
    assert not all_passed(check(candidate))
    candidate = example()
    candidate["tests"][0]["expected"] = 999
    outcomes = check(candidate)
    assert any(not c.passed and "999" in c.detail for c in outcomes)
