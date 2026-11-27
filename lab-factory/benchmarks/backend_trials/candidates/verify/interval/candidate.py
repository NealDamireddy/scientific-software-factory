"""Bounded interval verification for a local, single-variable measurement program."""

import ast
import math
import operator
from fractions import Fraction
from typing import NamedTuple


OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
MAX_DEPTH = 48
MAX_BOXES = 4096


class Subdivide(Exception):
    """A tighter interval may establish the claim."""


def number(value):
    if type(value) not in (int, float):
        raise ValueError
    converted = float(value)
    if not math.isfinite(converted) or converted != value:
        raise ValueError
    return converted


def compile_program(source):
    if not isinstance(source, str) or len(source) > 4096:
        raise ValueError
    root = ast.parse(source.strip(), mode="eval")
    if sum(1 for _ in ast.walk(root)) > 180:
        raise ValueError

    def visit(node):
        if isinstance(node, ast.Constant):
            return ("const", number(node.value))
        if isinstance(node, ast.Name) and node.id in ("x", "f"):
            return (node.id,)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            child = visit(node.operand)
            return child if isinstance(node.op, ast.UAdd) else ("neg", child)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return (type(node.op), visit(node.left), visit(node.right))
        raise ValueError

    return visit(root.body)


def point(expr, x, f):
    op = expr[0]
    if op == "const":
        return expr[1]
    if op == "x":
        return x
    if op == "f":
        return f
    left = point(expr[1], x, f)
    if op == "neg":
        return -left
    return number(OPS[op](left, point(expr[2], x, f)))


class Bounds(NamedTuple):
    lo: Fraction
    hi: Fraction

    def __neg__(self):
        return Bounds(-self.hi, -self.lo)

    def __add__(self, other):
        return Bounds(self.lo + other.lo, self.hi + other.hi)

    def __sub__(self, other):
        return self + -other

    def __mul__(self, other):
        def product(a, b):
            # Derivative bounds may have an infinite endpoint.
            return a * b if a and b else 0

        ends = [product(a, b) for a in self for b in other]
        return Bounds(min(ends), max(ends))

    def reciprocal(self):
        if self.lo <= 0 <= self.hi:
            raise Subdivide
        return Bounds(Fraction(1) / self.hi, Fraction(1) / self.lo)

    def power(self, n):
        if n < 0:
            return self.reciprocal().power(-n)
        if n == 0:
            return ONE
        a, b = self.lo ** n, self.hi ** n
        lower = 0 if n % 2 == 0 and self.lo <= 0 <= self.hi else min(a, b)
        return Bounds(lower, max(a, b))


def singleton(x):
    v = Fraction(x)
    return Bounds(v, v)


ZERO = singleton(0)
ONE = singleton(1)


def sqrt_bound(value, upper):
    if not value:
        return Fraction(0)
    # Enclose sqrt(p/q) on a dyadic grid, retaining at least 64 significant bits.
    value = Fraction(value)
    shift = max(0, 65 - (value.numerator.bit_length() - value.denominator.bit_length()) // 2)
    scaled = value * (1 << (2 * shift))
    root = math.isqrt(scaled.numerator // scaled.denominator)
    if upper and root * root < scaled:
        root += 1
    return Fraction(root, 1 << shift)


def powered(base, exponent, slope):
    n = Fraction(exponent)
    if n.denominator not in (1, 2) or abs(n) > 64:
        raise ValueError
    if n.denominator == 1:
        value = base.power(int(n))
        if slope == ZERO or not n:
            return value, ZERO
        return value, singleton(n) * base.power(int(n) - 1) * slope
    if base.lo < 0:
        raise Subdivide
    root = Bounds(sqrt_bound(base.lo, False), sqrt_bound(base.hi, True))
    value = root.power(n.numerator)
    if slope == ZERO:
        return value, ZERO
    if n == Fraction(1, 2) and root.lo == 0:
        multiplier = Bounds(Fraction(1, 2) / root.hi if root.hi else 0, math.inf)
    else:
        multiplier = singleton(n) * root.power(n.numerator - 2)
    return value, multiplier * slope


def rounded(value):
    """Round interval endpoints after each operation for runtime range checks."""
    try:
        return Bounds(Fraction(float(value.lo)), Fraction(float(value.hi)))
    except (ValueError, OverflowError):
        raise Subdivide from None


def enclose(expr, x, f, runtime, slopes):
    cache = {}

    def evaluate(term):
        if term in cache:
            return cache[term]
        op = term[0]
        if op == "const":
            result = singleton(term[1]), ZERO
        elif op == "x":
            result = x, ONE if slopes else ZERO
        elif op == "f":
            result = f, ZERO
        else:
            a, da = evaluate(term[1])
            if op == "neg":
                result = -a, -da
            else:
                b, db = evaluate(term[2])
                same = term[1] == term[2]
                if op is ast.Add:
                    result = a + b, da + db
                elif op is ast.Sub:
                    result = (ZERO, ZERO) if same else (a - b, da - db)
                elif op is ast.Mult:
                    result = a.power(2) if same else a * b, a * db + b * da
                elif op is ast.Div:
                    inv = b.reciprocal()
                    result = (ONE, ZERO) if same else (a * inv, (da * b - a * db) * inv.power(2))
                else:
                    if b.lo != b.hi or db != ZERO:
                        raise Subdivide
                    result = powered(a, b.lo, da)
            if runtime:
                result = rounded(result[0]), ZERO
            else:
                # Refuse exponential growth in exact rational intermediates.
                for bound in (*result[0], *result[1]):
                    if isinstance(bound, Fraction) and max(
                        bound.numerator.bit_length(), bound.denominator.bit_length()
                    ) > 8192:
                        raise ValueError
        cache[term] = result
        return result

    return evaluate(expr)


def certify(expr, domain, factor, properties, observed_x):
    stack = [(domain, 0)]
    f = singleton(factor)
    trend = "nondecreasing" in properties and domain.lo != domain.hi
    positive = "nonnegative" in properties
    if trend:
        # The derivative is for real arithmetic. Also check the actual floating
        # evaluator for reversals at the references and fixed-factor probes.
        probes = observed_x.union(
            float(domain.lo + (domain.hi - domain.lo) * i / 16) for i in range(17)
        )
        previous = -math.inf
        for x in sorted(probes):
            value = point(expr, x, factor)
            if value < previous:
                return False
            previous = value
    for _ in range(MAX_BOXES):
        if not stack:
            return True
        box, depth = stack.pop()
        try:
            values, _ = enclose(expr, box, f, runtime=True, slopes=False)
            if positive and values.hi < 0:
                return False
            if trend:
                _, derivative = enclose(expr, box, f, runtime=False, slopes=True)
                if derivative.hi < 0:
                    return False
            if (not positive or values.lo >= 0) and (not trend or derivative.lo >= 0):
                continue
        except Subdivide:
            pass
        if depth >= MAX_DEPTH or box.lo == box.hi:
            return False
        mid = (box.lo + box.hi) / 2
        stack.extend(((Bounds(mid, box.hi), depth + 1), (Bounds(box.lo, mid), depth + 1)))
    return not stack


def solve(request):
    withheld = {"decision": "withhold", "value": None}
    try:
        expr = compile_program(request["program"])
        lo, hi = map(number, request["domain"])
        properties = request.get("properties", [])
        if not isinstance(properties, (list, tuple)) or any(
            p not in ("nondecreasing", "nonnegative") for p in properties
        ):
            return withheld
        controls = request["controls"]
        if not isinstance(controls, (list, tuple)) or not controls:
            return withheld

        def measure(record):
            x, f = number(record["x"]), number(record["f"])
            if not lo <= x <= hi or f <= 0:
                raise ValueError
            value = point(expr, x, f)
            if "nonnegative" in properties and value < 0:
                raise ValueError
            return value, x, f

        sample, sample_x, factor = measure(request["sample"])
        observations = {factor: {sample_x}}
        for control in controls:
            observed, x, f = measure(control)
            expected, tolerance = number(control["expected"]), number(control["tolerance"])
            if tolerance < 0 or abs(Fraction(observed) - Fraction(expected)) > tolerance:
                return withheld
            observations.setdefault(f, set()).add(x)

        domain = Bounds(Fraction(lo), Fraction(hi))
        if all(certify(expr, domain, f, properties, xs) for f, xs in observations.items()):
            return {"decision": "release", "value": sample}
    except (ArithmeticError, KeyError, TypeError, ValueError, SyntaxError, RecursionError):
        pass
    return withheld
