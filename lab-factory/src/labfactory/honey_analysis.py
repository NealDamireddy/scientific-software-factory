"""Interpret a submitted table analysis and check it against published honey data."""

from bisect import bisect_left
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import math

from .checks import CheckResult


SOURCE_IDS = ("hanna-hi96800-manual", "hanna-honey-refractive-index",
              "ihc-2009-honey-moisture", "barbour-2026-honey-moisture")
# The source table spans 1.4740–1.5044. The HI96800 nD20 scale ends at 1.5040.
_MIN = Decimal("1.4740")
_MAX = Decimal("1.5040")

# Independent reference from IHC (2009), method 1, p. 11. The first digest
# covers the 61 ascending 'index in 0.0001:water in tenths' pairs. The second
# covers the 601 possible duplicate means in ascending order, interpolated
# using exact fractions and rounded half-up to integer tenths. Join with ','.
_TABLE_DIGEST = "c51c3b56aa0eaa60a11e09507aca04038f4a0fc5a122c7a4939c56e1500dbece"
_REFERENCE_DIGEST = "1ebf385a73dc5cfc11112b901c711da189f94eb347fe46b6c1af182d482535a5"


def _digest(strings):
    return sha256(",".join(strings).encode("ascii")).hexdigest()


def _number(value):
    try:
        if type(value) in (int, float) and math.isfinite(value):
            return Decimal(str(value))
    except (OverflowError, ValueError):
        pass
    raise ValueError("Use finite JSON numbers.")


def _on_grid(value, scale):
    return scale % value.as_integer_ratio()[1] == 0


def _readings(values):
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Enter two simulated nD20 readings at 20 °C.")
    pair = [_number(x) for x in values]
    if not all(_on_grid(x, 10000) for x in pair):
        raise ValueError("The HI96800 reports nD20 in increments of 0.0001.")
    return pair


def _within_range(pair):
    return all(_MIN <= n <= _MAX for n in pair)


def _program(artifact):
    if not isinstance(artifact, dict) or set(artifact) != {"algorithm", "table", "citations", "tests"}:
        raise ValueError("Supply algorithm, table, citations and tests.")
    steps = artifact["algorithm"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("Supply one to eight analysis operations.")
    for step in steps:
        if step == {"op": "mean"} or step == {"op": "interpolate", "table": "table"}:
            continue
        if (isinstance(step, dict) and set(step) == {"op", "places"} and step["op"] == "round"
                and type(step["places"]) is int and 0 <= step["places"] <= 6):
            continue
        raise ValueError("Use mean, interpolate with the submitted table, or round to 0–6 decimal places.")

    raw = artifact["table"]
    if not isinstance(raw, list) or len(raw) != 61:
        raise ValueError("The complete cited honey table contains 61 pairs.")
    indices, moisture = [], []
    for row in raw:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("Each table row needs a refractive index and water mass percentage.")
        n, w = map(_number, row)
        if not (1 < n < 2 and _on_grid(n, 10000) and 0 <= w <= 100 and _on_grid(w, 10)):
            raise ValueError("Check the table units and precision against the publication.")
        if indices and n <= indices[-1]:
            raise ValueError("Sort the refractive-index column in strictly increasing order.")
        indices.append(n)
        moisture.append(w)
    return steps, indices, moisture


def _execute(program, pair):
    steps, indices, moisture = program
    value = pair
    for step in steps:
        if step["op"] == "mean":
            if not isinstance(value, list):
                raise ValueError("Mean requires the input readings.")
            value = sum(value) / len(value)
        elif step["op"] == "interpolate":
            if isinstance(value, list) or not indices[0] <= value <= indices[-1]:
                raise ValueError("Interpolation requires one index within the submitted table.")
            right = max(1, bisect_left(indices, value))
            left = right - 1
            fraction = (value - indices[left]) / (indices[right] - indices[left])
            value = moisture[left] + fraction * (moisture[right] - moisture[left])
        else:
            if isinstance(value, list):
                raise ValueError("Rounding requires one numeric result.")
            value = value.quantize(Decimal(1).scaleb(-step["places"]), rounding=ROUND_HALF_UP)
    if not isinstance(value, Decimal):
        raise ValueError("The analysis must return one water mass percentage.")
    return value


def _text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def _authored_tests(artifact, program):
    cases = artifact["tests"]
    if not isinstance(cases, list) or not 3 <= len(cases) <= 16:
        raise ValueError("Supply 3–16 agent-written numerical tests.")
    results, inputs = [], set()
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"label", "readings", "expected"}
                or not _text(case["label"], 160)):
            raise ValueError("Each test needs a short label, two readings and an expected moisture value.")
        pair = _readings(case["readings"])
        if not _within_range(pair):
            raise ValueError("Use in-range simulated readings for the submitted numerical tests.")
        inputs.add(tuple(sorted(pair)))
        expected = _number(case["expected"])
        actual = _execute(program, pair)
        results.append(CheckResult("Agent test · " + case["label"], actual == expected,
                                   f"{pair[0]} and {pair[1]} nD20: expected {expected}, got {actual} g/100 g."))
    if len(inputs) < 3:
        raise ValueError("Supply at least three distinct test inputs.")
    return results


def check(artifact):
    try:
        program = _program(artifact)
        citations = artifact["citations"]
        if (not isinstance(citations, list) or len(citations) != len(SOURCE_IDS)
                or any(not isinstance(c, dict) or set(c) != {"id", "use"}
                       or not _text(c["id"], 100) or not _text(c["use"], 1200) for c in citations)
                or {c["id"] for c in citations} != set(SOURCE_IDS)):
            raise ValueError("Cite the manual, both published methods and the paper, explaining each role.")
        _, indices, moisture = program
        digest = _digest(f"{int(n * 10000)}:{int(w * 10)}" for n, w in zip(indices, moisture))
        table_ok = digest == _TABLE_DIGEST
        results = [CheckResult("Independent published table", table_ok,
                               "All 61 pairs match IHC method 1, page 11." if table_ok else
                               "A table value differs from IHC method 1, page 11.")]
        results.extend(_authored_tests(artifact, program))
        outputs = []
        for half_tick in range(29480, 30081):
            pair = [Decimal(half_tick // 2) / 10000, Decimal((half_tick + 1) // 2) / 10000]
            result = _execute(program, pair)
            if not _on_grid(result, 10):
                raise ValueError("Report the simulated moisture to one decimal place.")
            outputs.append(str(int(result * 10)))
        matches = _digest(outputs) == _REFERENCE_DIGEST
        results.append(CheckResult("Independent numerical sweep", matches,
                                   "All 601 reportable mean indices match the independent reference." if matches else
                                   "Results differ from the independent interpolation and rounding reference."))
        return results
    except (ValueError, ArithmeticError) as exc:
        return [CheckResult("Honey analysis", False, str(exc))]


def evaluate(artifact, readings):
    pair = _readings(readings)
    result = {"status": "withheld", "mean_refractive_index": float(sum(pair) / 2), "moisture_pct": None,
              "reason": ""}
    if not _within_range(pair):
        result["reason"] = "Each nD20 reading must lie within 1.4740–1.5040 for this honey method and meter."
        return result
    moisture = _execute(_program(artifact), pair)
    return {**result, "status": "estimated", "moisture_pct": float(moisture)}
