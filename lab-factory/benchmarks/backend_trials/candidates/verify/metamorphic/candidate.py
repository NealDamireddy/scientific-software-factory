"""Verify simulated numeric measurements with fixed-factor metamorphic probes."""

import ast
import math
import operator


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("expected a finite real number")
    return value


def _power(base, exponent):
    if type(base) is int and type(exponent) is int and abs(base) >= 2 and exponent > 1023:
        raise ValueError("power exceeds finite measurement range")
    return base ** exponent


_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: _power, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _interpreter(source):
    """Build arithmetic functions and collect x-independent offsets for probes."""
    if not isinstance(source, str):
        raise ValueError("expected an expression")
    offsets = []

    def visit(node):
        if isinstance(node, ast.Name) and node.id == "x":
            return (lambda x, f: x), True
        if isinstance(node, ast.Name) and node.id == "f":
            fn, varies = (lambda x, f: f), False
        elif isinstance(node, ast.Constant):
            value = _number(node.value)
            fn, varies = (lambda x, f: value), False
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            operand, varies = visit(node.operand)
            op = _UNARY[type(node.op)]
            fn = lambda x, f: _number(op(operand(x, f)))
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, left_varies = visit(node.left)
            right, right_varies = visit(node.right)
            op = _BINARY[type(node.op)]
            fn = lambda x, f: _number(op(left(x, f), right(x, f)))
            varies = left_varies or right_varies
        else:
            raise ValueError("unsupported expression")
        if not varies:
            offsets.append(fn)
        return fn, varies

    evaluate, _ = visit(ast.parse(source.strip(), mode="eval").body)
    return evaluate, offsets


def _interpolate(a, b, fraction):
    if (a < 0) != (b < 0):
        return a * (1 - fraction) + b * fraction
    return a + (b - a) * fraction


def _probe_points(lo, hi, observed, offsets, factor):
    anchors = {lo, hi, *observed}
    if lo <= 0 <= hi:
        anchors.add(0)
    for offset in offsets:
        value = offset(lo, factor)
        for center in (value, -value):
            if lo <= center <= hi:
                anchors.add(center)

    points = set(anchors)
    # A grid boundary and an off-center partner in every interval. Vary the
    # partner's position deterministically to avoid a second equally spaced grid.
    for cell in range(128):
        jitter = (1 + (cell * 37) % 127) / 128
        points.add(_interpolate(lo, hi, cell / 128))
        points.add(_interpolate(lo, hi, (cell + jitter) / 128))

    # Probe both sides of data and expression landmarks at several scales.
    for center in anchors:
        for edge in (lo, hi):
            if edge != center:
                points.add(math.nextafter(center, edge))
                for scale in (2**-4, 2**-10, 2**-20, 2**-32):
                    points.add(_interpolate(center, edge, scale))
    return sorted(x for x in points if lo <= x <= hi)


def _point(record, lo, hi):
    x, factor = _number(record["x"]), _number(record["f"])
    if not lo <= x <= hi or factor <= 0:
        raise ValueError("point outside the measurement domain")
    return x, factor


def _refine_minimum(evaluate, factor, left, center, right, value):
    """Probe a sampled local minimum for a sub-grid sign violation."""
    for _ in range(64):
        a = _interpolate(left, center, 0.5)
        b = _interpolate(center, right, 0.5)
        if (a, b) == (left, right) or a == b:
            break
        va, vb = evaluate(a, factor), evaluate(b, factor)
        yield a, va
        yield b, vb
        if min(va, vb) < 0:
            raise ValueError("negative value near a sampled minimum")
        if va < value and va <= vb:
            right, center, value = center, a, va
        elif vb < value:
            left, center, value = center, b, vb
        else:
            left, right = a, b


def _verify(request):
    evaluate, offsets = _interpreter(request["program"])
    lo, hi = map(_number, request["domain"])
    sample_x, sample_f = _point(request["sample"], lo, hi)
    properties = request.get("properties", [])
    if isinstance(properties, str):
        properties = [properties]
    if not isinstance(properties, (list, tuple)) or any(
        prop not in ("nondecreasing", "nonnegative") for prop in properties
    ):
        raise ValueError("unsupported property declaration")

    by_factor = {sample_f: {sample_x}}
    controls_x = set()
    for control in request["controls"]:
        x, factor = _point(control, lo, hi)
        expected = _number(control["expected"])
        tolerance = _number(control["tolerance"])
        if tolerance < 0 or abs(evaluate(x, factor) - expected) > tolerance:
            raise ValueError("control failed")
        controls_x.add(x)
        by_factor.setdefault(factor, set()).add(x)
    if len(controls_x) < 2:
        raise ValueError("insufficient independent controls")

    trend = "nondecreasing" in properties
    sign = "nonnegative" in properties
    for factor, observed in by_factor.items():
        points = _probe_points(lo, hi, observed, offsets, factor)
        values = [evaluate(x, factor) for x in points]
        if sign:
            if min(values) < 0:
                raise ValueError("nonnegative property failed")
            readings = dict(zip(points, values))
            for i in range(1, len(points) - 1):
                a, b, c = values[i - 1:i + 2]
                if b <= min(a, c) and b < max(a, c):
                    readings.update(_refine_minimum(evaluate, factor, *points[i - 1:i + 2], b))
            if trend:
                values = [readings[x] for x in sorted(readings)]
        if trend and any(a > b for a, b in zip(values, values[1:])):
            raise ValueError("nondecreasing property failed")
    return {"decision": "release", "value": evaluate(sample_x, sample_f)}


def solve(request):
    try:
        return _verify(request)
    except (ArithmeticError, KeyError, TypeError, ValueError, SyntaxError, RecursionError):
        return {"decision": "withhold", "value": None}
