from copy import deepcopy
import json
from pathlib import Path

import pytest

from labfactory.checks import all_passed
from labfactory.honey_analysis import check, evaluate


@pytest.fixture
def candidate():
    path = Path(__file__).resolve().parents[1] / "examples" / "honey-analysis.json"
    return json.loads(path.read_text())


def test_authored_program_passes_published_reference_and_its_own_tests(candidate):
    results = check(candidate)
    assert all_passed(results), results
    assert sum(r.name.startswith("Agent test") for r in results) == len(candidate["tests"])
    assert any("601" in r.detail for r in results)
    assert any("61 pairs" in r.detail for r in results)


@pytest.mark.parametrize(("readings", "expected"), [
    ([1.4865, 1.4865], 20.0), ([1.474, 1.474], 25.0), ([1.504, 1.504], 13.1),
    ([1.4914, 1.4916], 18.0), ([1.4944, 1.4945], 16.9),
    # A nonuniform stretch in the original table. Averaging converted moisture
    # instead of converting the mean index would give a different result.
    ([1.474, 1.504], 19.0),
])
def test_simulated_results(candidate, readings, expected):
    result = evaluate(candidate, readings)
    assert result["moisture_pct"] == expected and result["status"] == "estimated"
    assert result["mean_refractive_index"] == pytest.approx(sum(readings) / 2)
    assert evaluate(candidate, readings[::-1]) == result


@pytest.mark.parametrize("readings", [[1.4739, 1.50], [1.49, 1.5041], [80, 80]])
def test_each_reading_has_to_fit_meter_and_chart(candidate, readings):
    result = evaluate(candidate, readings)
    assert result["status"] == "withheld" and result["moisture_pct"] is None
    assert "1.4740–1.5040" in result["reason"]


@pytest.mark.parametrize("readings", [[], [1.49], [1.49] * 3, [True, 1.49], ["1.49", 1.49],
                                      [1.49001, 1.49001], [float("nan"), 1.49], [float("inf"), 1.49]])
def test_malformed_simulated_input(candidate, readings):
    with pytest.raises(ValueError):
        evaluate(candidate, readings)


def test_independent_checks_catch_wrong_row_that_agent_tests_miss(candidate):
    candidate["table"][5][1] += 0.5
    results = check(candidate)
    assert all(r.passed for r in results if r.name.startswith("Agent test"))
    assert {r.name for r in results if not r.passed} == {
        "Independent published table", "Independent numerical sweep"
    }


def test_interpreter_runs_submitted_operations(candidate):
    # Prematurely rounding the index changes the answer. Both the submitted tests
    # and the independent reference are used to detect changes to the program.
    candidate["algorithm"].insert(1, {"op": "round", "places": 3})
    assert evaluate(candidate, [1.4915, 1.4915])["moisture_pct"] == 17.8
    assert not all_passed(check(candidate))


@pytest.mark.parametrize("mutation", ["op", "citation", "expected", "repeated", "unsorted"])
def test_invalid_submissions_produce_reviewer_visible_failures(candidate, mutation):
    if mutation == "op":
        candidate["algorithm"] = [{"op": "unknown"}]
    elif mutation == "citation":
        candidate["citations"][0] = candidate["citations"][1]
    elif mutation == "expected":
        candidate["tests"][0]["expected"] = 1
    elif mutation == "repeated":
        candidate["tests"] = [deepcopy(candidate["tests"][0]) for _ in range(3)]
    elif mutation == "unsorted":
        candidate["table"].reverse()
    results = check(candidate)
    assert not all_passed(results) and all(r.detail for r in results)
