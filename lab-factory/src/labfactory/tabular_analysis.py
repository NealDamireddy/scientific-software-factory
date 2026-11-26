"""Bounded numerical Python for one anonymous sample and public calibration standards.

Only the syntax interpreted below is available to submitted code. It receives
plain numbers, with a fresh environment for every sample, including controls.
"""

from __future__ import annotations

import ast
from decimal import Decimal
import math
import operator
from statistics import StatisticsError, linear_regression

from .checks import CheckResult


INSTRUCTIONS = (
    "Submit an object with source (actual Python), explanation (how you used the protocol, "
    "calibration and units), and tests (2–12 distinct self-authored numerical cases). Each "
    "test is {label, standards, signal, factor, expected}. Standards are an array of [signal, "
    "known] pairs, including in tests. Implement exactly def analyze(standards, signal, factor): "
    "with local assignments followed by one numeric return. Each call receives a single numerical "
    "signal, positive row factor, and the batch standards. Choose operations from the protocol. "
    "Available primitives are: column(standards, i) with i=0 for signal or 1 for known value; "
    "vector[i] and standards[i][j] with zero-based integer indices; slope(x,y), intercept(x,y) "
    "for ordinary least squares y on x with a fitted intercept; min(v), max(v), mean(v), sum(v), "
    "len(v); abs(x), sqrt(x), log(x) (natural), log10(x), exp(x), round(x,n); +, -, *, /, **. "
    "Do not import modules, define extra functions, use loops or depend on sample identities. "
    "Author two or more test cases with numeric expected results obtained independently of the "
    "submitted source. A separate verifier checks an anonymous control."
)

MAX_STANDARDS = 256
SOURCE_LIMIT = 8192
_INPUTS = ("standards", "signal", "factor")
_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_SCALAR_FUNCTIONS = {"sqrt": math.sqrt, "abs": abs, "log": math.log, "log10": math.log10, "exp": math.exp}
_FUNCTIONS = {*_SCALAR_FUNCTIONS, "column", "slope", "intercept", "min", "max", "sum", "mean", "len", "round"}


def _number(value):
    if type(value) in (int, float):
        try:
            scalar = float(value)
            if math.isfinite(scalar):
                return scalar
        except OverflowError:
            pass
    raise ValueError("Expected a finite numeric value.")


def _integer(value):
    number = _number(value)
    if not number.is_integer():
        raise ValueError("An index or decimal-place count must be an integer.")
    return int(number)


def _standards(rows):
    if not isinstance(rows, list) or len(rows) > MAX_STANDARDS:
        raise ValueError(f"Supply at most {MAX_STANDARDS} numeric standard pairs.")
    pairs = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("Each standard needs a signal and a known value.")
        pairs.append(tuple(map(_number, row)))
    return tuple(pairs)


def _body(source):
    if not isinstance(source, str) or len(source) > SOURCE_LIMIT:
        raise ValueError(f"Supply Python source of at most {SOURCE_LIMIT} characters.")
    try:
        module = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, UnicodeError):
        raise ValueError("Cannot parse the submitted Python source.") from None
    if sum(1 for _ in ast.walk(module)) > 256:
        raise ValueError("The source exceeds 256 syntax nodes.")
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise ValueError("Supply one function: def analyze(standards, signal, factor):")
    function = module.body[0]
    args = function.args
    if (function.name != "analyze" or tuple(arg.arg for arg in args.args) != _INPUTS
            or function.decorator_list or function.returns or getattr(function, "type_params", None)
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults
            or any(arg.annotation for arg in args.args)):
        raise ValueError("Use the exact signature def analyze(standards, signal, factor):")
    body = function.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body or not isinstance(body[-1], ast.Return) or body[-1].value is None:
        raise ValueError("End the function with one numeric return.")
    for stmt in body[:-1]:
        if (not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1
                or not isinstance(stmt.targets[0], ast.Name) or stmt.targets[0].id in (*_INPUTS, *_FUNCTIONS)):
            raise ValueError("Use assignments to named local values before the final return.")
    return body


def _vector(value):
    if not isinstance(value, tuple) or not value or any(type(item) is not float for item in value):
        raise ValueError("Supply a nonempty numeric vector, such as a column of standards.")
    return value


def _call(name, args, environment):
    if name == "column" and len(args) == 2:
        index = _integer(args[1])
        if args[0] is not environment["standards"] or index not in (0, 1):
            raise ValueError("Use column(standards, 0) or column(standards, 1).")
        return tuple(row[index] for row in args[0])
    if name in ("slope", "intercept") and len(args) == 2:
        fit = linear_regression(_vector(args[0]), _vector(args[1]))
        return _number(fit.slope if name == "slope" else fit.intercept)
    if name in _SCALAR_FUNCTIONS and len(args) == 1:
        return _number(_SCALAR_FUNCTIONS[name](_number(args[0])))
    if name == "round" and len(args) == 2:
        precision = _integer(args[1])
        if abs(precision) > 12:
            raise ValueError("Round to between -12 and 12 decimal places.")
        return round(_number(args[0]), precision)
    if name == "len" and len(args) == 1 and isinstance(args[0], tuple):
        return float(len(args[0]))
    if name in ("min", "max", "mean", "sum") and len(args) == 1:
        vector = _vector(args[0])
        if name in ("min", "max"):
            return min(vector) if name == "min" else max(vector)
        total = math.fsum(vector)
        return _number(total / len(vector) if name == "mean" else total)
    raise ValueError("Unsupported function or argument count in the submitted source.")


def _expression(node, environment):
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.Name) and node.id in environment:
        return environment[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _number(_expression(node.operand, environment))
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in (*_OPERATORS, ast.Pow):
        left = _number(_expression(node.left, environment))
        right = _number(_expression(node.right, environment))
        if isinstance(node.op, ast.Pow):
            if abs(right) > 64:
                raise ValueError("The power exponent must be between -64 and 64.")
            return _number(math.pow(left, right))
        return _number(_OPERATORS[type(node.op)](left, right))
    if isinstance(node, ast.Subscript):
        rows = _expression(node.value, environment)
        index = _integer(_expression(node.slice, environment))
        if not isinstance(rows, tuple) or not 0 <= index < len(rows):
            raise ValueError("Index outside the available data.")
        return rows[index]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS and not node.keywords):
        return _call(node.func.id, [_expression(arg, environment) for arg in node.args], environment)
    raise ValueError(f"Unsupported numeric expression on line {node.lineno}.")


def _run(body, standards, signal, factor, range_gate):
    pairs = _standards(standards)
    sample = _number(signal)
    multiplier = _number(factor)
    if multiplier <= 0:
        raise ValueError("The row factor must be positive.")
    if range_gate:
        domain = [x for x, _ in pairs]
        if not domain or not min(domain) <= sample <= max(domain):
            raise ValueError("The signal is outside the batch calibration range.")
    env = {"standards": pairs, "signal": sample, "factor": multiplier}
    try:
        for stmt in body:
            value = _expression(stmt.value, env)
            if isinstance(stmt, ast.Return):
                return _number(value)
            env[stmt.targets[0].id] = value
    except (ArithmeticError, StatisticsError) as exc:
        raise ValueError(f"Numerical calculation failed: {exc}") from None
    raise ValueError("The analysis must return a number.")


def _payload(artifact):
    if not isinstance(artifact, dict) or set(artifact) != {"source", "explanation", "tests"}:
        raise ValueError("Supply source, explanation and tests.")
    return _body(artifact["source"])


def check(artifact):
    """Public checks use only numerical examples supplied by the author."""
    try:
        body = _payload(artifact)
        explanation = artifact["explanation"]
        if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 6000:
            raise ValueError("Supply an explanation of at most 6000 characters.")
        tests = artifact["tests"]
        if not isinstance(tests, list) or not 2 <= len(tests) <= 12:
            raise ValueError("Supply 2–12 numerical tests.")
        checks, inputs = [], set()
        for test in tests:
            if (not isinstance(test, dict) or set(test) != {"label", "standards", "signal", "factor", "expected"}
                    or not isinstance(test["label"], str) or not test["label"].strip() or len(test["label"]) > 160):
                raise ValueError("Each numerical test needs a label, standards, signal, factor and expected value.")
            expected = _number(test["expected"])
            inputs.add((_standards(test["standards"]), _number(test["signal"]), _number(test["factor"])))
            actual = _run(body, test["standards"], test["signal"], test["factor"], False)
            checks.append(CheckResult("Agent test · " + test["label"], math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10),
                                      f"Expected {expected:.12g}, got {actual:.12g}."))
        if len(inputs) < 2:
            raise ValueError("Supply at least two distinct test inputs.")
        return checks
    except ValueError as exc:
        return [CheckResult("Submitted numerical analysis", False, str(exc))]


def evaluate(artifact, standards, signal, factor=1.0, *, range_gate=True):
    """Execute one anonymous observation through the candidate's actual program."""
    return _run(_payload(artifact), standards, signal, factor, range_gate)


def verify_control(artifact, standards, signal, factor, expected, tolerance, *, range_gate=True):
    """Reviewer-only comparison. Keep this object outside agent context and replies."""
    truth = _number(expected)
    limit = _number(tolerance)
    if limit < 0:
        raise ValueError("The absolute control tolerance must be nonnegative.")
    report = {"passed": False, "predicted": None, "expected": truth, "tolerance": limit, "error": None, "reason": ""}
    try:
        prediction = evaluate(artifact, standards, signal, factor, range_gate=range_gate)
        # Compare the exact decimal representations shown in the reviewer receipt.
        error = abs(Decimal(str(prediction)) - Decimal(str(truth)))
        report.update(predicted=prediction, error=_number(float(error)), passed=error <= Decimal(str(limit)))
        if not report["passed"]:
            report["reason"] = "Absolute prediction error exceeds the frozen tolerance."
    except ValueError as exc:
        report["reason"] = str(exc)
    return report
