"""Verify a simulated measurement against independent controls and declared properties."""

import ast
import math
import operator
from fractions import Fraction


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: math.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_PROPERTIES = {"nonnegative", "nondecreasing"}
_GRID_INTERVALS = 1024


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("expected a finite number")
    return float(value)


def _program(source):
    if not isinstance(source, str) or len(source) > 8192:
        raise ValueError("invalid expression")
    root = ast.parse(source.strip(), mode="eval").body
    if sum(1 for _ in ast.walk(root)) > 512:
        raise ValueError("expression too large")
    return root


def _evaluate(node, x, f):
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.Name) and node.id in ("x", "f"):
        return x if node.id == "x" else f
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand, x, f))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left, x, f)
        right = _evaluate(node.right, x, f)
        return _number(_BINARY[type(node.op)](left, right))
    raise ValueError("unsupported expression")


def _point(record, lo, hi):
    x = _number(record["x"])
    f = _number(record["f"])
    if not lo <= x <= hi or f <= 0:
        raise ValueError("invalid measurement coordinates")
    return x, f


def _properties(declared):
    if isinstance(declared, str):
        declared = [declared]
    if isinstance(declared, dict):
        invalid_flags = any(type(flag) is not bool for flag in declared.values())
        if set(declared) - _PROPERTIES or invalid_flags:
            raise ValueError("invalid property flags")
        declared = [key for key, enabled in declared.items() if enabled]
    if not isinstance(declared, (list, tuple)):
        raise ValueError("invalid properties")
    names = set(declared)
    if names - _PROPERTIES:
        raise ValueError("unknown property")
    return names


def _within_tolerance(observed, expected, tolerance):
    # Compare the decimal representations exactly at inclusive tolerance boundaries.
    residual = abs(Fraction(str(observed)) - Fraction(str(expected)))
    return residual <= Fraction(str(tolerance))


def _screen(program, lo, hi, points, properties):
    xs = {x for x, _ in points}
    for i in range(_GRID_INTERVALS + 1):
        t = i / _GRID_INTERVALS
        # A convex combination also works when the width hi - lo overflows.
        x = (1.0 - t) * lo + t * hi
        xs.add(min(hi, max(lo, x)))
    ordered_xs = sorted(xs)
    for f in sorted({f for _, f in points}):
        previous = None
        for x in ordered_xs:
            current = _evaluate(program, x, f)
            if "nonnegative" in properties and current < 0:
                return False
            if "nondecreasing" in properties and previous is not None and current < previous:
                return False
            previous = current
    return True


def solve(request):
    """Return the sample value only when the entire control panel passes."""
    withhold = {"decision": "withhold", "value": None}
    try:
        domain = request["domain"]
        if not isinstance(domain, (list, tuple)) or len(domain) != 2:
            return withhold
        lo, hi = map(_number, domain)
        sample = _point(request["sample"], lo, hi)
        program = _program(request["program"])
        properties = _properties(request.get("properties", []))
        controls = request["controls"]
        if not isinstance(controls, (list, tuple)) or len(controls) < 2:
            return withhold

        points = []
        for record in controls:
            x, f = _point(record, lo, hi)
            expected = _number(record["expected"])
            tolerance = _number(record["tolerance"])
            observed = _evaluate(program, x, f)
            if tolerance < 0 or not _within_tolerance(observed, expected, tolerance):
                return withhold
            points.append((x, f))
        if len({x for x, _ in points}) < 2:
            return withhold

        value = _evaluate(program, *sample)
        if properties and not _screen(program, lo, hi, points + [sample], properties):
            return withhold
        return {"decision": "release", "value": value}
    except (ArithmeticError, KeyError, RecursionError, SyntaxError, TypeError, ValueError):
        return withhold
