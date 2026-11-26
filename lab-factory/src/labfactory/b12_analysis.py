"""Frozen simulation calibration, arithmetic interpreter and independent B12 checks."""

from __future__ import annotations

import ast
import math
import operator
from statistics import mean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .checks import CheckResult


CALIBRATION = {
    "id": "b12-sim-550-v1",
    "wavelength_nm": 550,
    "slope_au_per_mg_l": 0.0064,
    "intercept_au": 0.0,
    "min_au": 0.0192,
    "max_au": 0.1536,
}
SAMPLE_READINGS = [0.1020, 0.1024, 0.1028]
MAX_SOURCE_CHARS = 4096

# Expected concentrations are specified independently of the submitted program.
# Asymmetric triplicates distinguish the mean from a single reading or the median.
_REFERENCE_CASES = (
    ("Lower calibration endpoint", [0.0192] * 3, 0.0064, 0, 3),
    ("Upper calibration endpoint", [0.1536] * 3, 0.0064, 0, 24),
    ("Asymmetric triplicate", [0.020, 0.030, 0.046], 0.0064, 0, 5),
    ("Alternate slope", [0.029, 0.033, 0.034], 0.004, 0, 8),
    ("Nonzero intercept", [0.060, 0.061, 0.065], 0.004, 0.012, 12.5),
)
_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_INPUTS = ("readings", "slope", "intercept")


def validate_readings(readings: object) -> list[float]:
    if not isinstance(readings, list) or len(readings) != 3:
        raise ValueError("Enter exactly three simulated absorbance readings in AU.")
    values = []
    for index, value in enumerate(readings, 1):
        try:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError
            values.append(float(value))
        except (ValueError, OverflowError):
            raise ValueError(f"Replicate {index} must be a finite number in AU.") from None
    return values


def _program(source: str) -> list[ast.stmt]:
    if not isinstance(source, str) or len(source) > MAX_SOURCE_CHARS:
        raise ValueError(f"Submit a Python source string of at most {MAX_SOURCE_CHARS} characters.")
    if any(c not in "\n\t" and not (" " <= c <= "~") for c in source.replace("\r\n", "\n")):
        raise ValueError("Use printable ASCII Python source.")
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        line = getattr(exc, "lineno", None)
        where = f" on line {line}" if line else ""
        raise ValueError(f"Cannot parse the candidate Python source{where}.") from None
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise ValueError("Submit one function named analyze(readings, slope, intercept).")
    if sum(1 for _ in ast.walk(module)) > 192:
        raise ValueError("The source exceeds the 192-node arithmetic profile.")
    function = module.body[0]
    args = function.args
    if (function.name != "analyze" or tuple(arg.arg for arg in args.args) != _INPUTS
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or function.decorator_list or function.returns or getattr(function, "type_params", None)
            or any(arg.annotation for arg in args.args)):
        raise ValueError("Use the signature def analyze(readings, slope, intercept):")
    body = function.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
        raise ValueError("End the function with one numeric return expression.")
    for statement in body[:-1]:
        if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                or not isinstance(statement.targets[0], ast.Name)):
            raise ValueError("Use only assignments to local numbers before the final return.")
        if statement.targets[0].id in (*_INPUTS, "sum", "len"):
            raise ValueError("Input names and the sum and len functions are reserved.")
    return body


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ArithmeticError("The analysis produced a non-finite number.")
    return value


def _expression(node: ast.expr, readings: list[float], numbers: dict[str, float]) -> float:
    # Only the operations below have an implementation. All operands are host
    # floats or the host's fixed triplicate. The AST is never dispatched to Python.
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _finite(float(node.value))
    if isinstance(node, ast.Name) and node.id in numbers:
        return numbers[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _expression(node.operand, readings, numbers)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left = _expression(node.left, readings, numbers)
        right = _expression(node.right, readings, numbers)
        return _finite(_OPERATORS[type(node.op)](left, right))
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "readings"
            and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int
            and 0 <= node.slice.value < 3):
        return readings[node.slice.value]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords
            and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "readings"):
        if node.func.id == "sum":
            return _finite(sum(readings))
        if node.func.id == "len":
            return float(len(readings))
    raise ValueError(f"Unsupported expression on line {node.lineno}. Use numeric arithmetic and the supplied inputs.")


def _run(program: list[ast.stmt], readings: list[float], slope: float, intercept: float) -> float:
    numbers = {"slope": float(slope), "intercept": float(intercept)}
    for statement in program:
        value = _expression(statement.value, readings, numbers)
        if isinstance(statement, ast.Return):
            return value
        numbers[statement.targets[0].id] = value
    raise ValueError("Missing numeric return.")


def _matches(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9)


def check_source(source: str) -> list[CheckResult]:
    from .checks import CheckResult

    try:
        program = _program(source)
    except ValueError as exc:
        return [CheckResult("Python arithmetic profile", False, str(exc))]
    checks = []
    for title, readings, slope, intercept, expected in _REFERENCE_CASES:
        inputs = f"readings {readings} AU, slope {slope}, intercept {intercept}"
        try:
            actual = _run(program, readings, slope, intercept)
        except ValueError as exc:
            return [CheckResult("Python arithmetic profile", False, str(exc))]
        except ArithmeticError as exc:
            checks.append(CheckResult(title, False, f"{inputs}: expected {expected} mg/L; calculation failed ({exc})."))
        else:
            checks.append(CheckResult(
                title, _matches(actual, expected), f"{inputs}: expected {expected} mg/L, got {actual:.12g} mg/L.",
            ))
    return checks


def analyze_readings(source: str, readings: object) -> dict:
    values = validate_readings(readings)
    mean_au = mean(values)
    result = {"status": "withheld", "concentration_mg_l": None, "mean_absorbance_au": mean_au, "reason": ""}
    low, high = CALIBRATION["min_au"], CALIBRATION["max_au"]
    for index, value in enumerate(values, 1):
        if not low <= value <= high:
            result["reason"] = f"Replicate {index} ({value} AU) is outside the simulated calibration [{low}, {high}] AU."
            return result
    slope, intercept = CALIBRATION["slope_au_per_mg_l"], CALIBRATION["intercept_au"]
    try:
        estimate = _run(_program(source), values, slope, intercept)
    except (ValueError, ArithmeticError) as exc:
        result["reason"] = f"The reviewed analysis could not return a finite concentration: {exc}"
        return result
    if not _matches(estimate, (mean_au - intercept) / slope):
        result["reason"] = "The analysis output disagrees with the independent calibration reference for these readings."
        return result
    result.update(status="estimated", concentration_mg_l=estimate)
    return result
