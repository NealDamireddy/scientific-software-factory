"""Offline, bounded protocol compiler for scalar tabular measurements."""

import ast
import math
import re
from typing import NamedTuple


class NeedInput(ValueError):
    pass


class Unit(NamedTuple):
    # Exponents of mass, volume, and amount of substance, in g, L, and mol.
    dimensions: tuple
    scale: float

    def combine(self, other, sign):
        powers = tuple(x + sign * y for x, y in zip(self.dimensions, other.dimensions))
        return Unit(powers, self.scale * other.scale ** sign)

    def conversion(self, other):
        if self.dimensions != other.dimensions:
            raise NeedInput("How should the calculated quantity be converted to the requested dimension?")
        return self.scale / other.scale


ONE = Unit((0, 0, 0), 1)
UNITS = {}
for dimension, names in enumerate((
    {"kg": 1000, "g": 1, "mg": 1e-3, "ug": 1e-6, "ng": 1e-9, "pg": 1e-12},
    {"l": 1, "dl": 0.1, "cl": 0.01, "ml": 1e-3, "ul": 1e-6, "nl": 1e-9},
    {"mol": 1, "mmol": 1e-3, "umol": 1e-6, "nmol": 1e-9},
)):
    for name, scale in names.items():
        UNITS[name] = Unit(tuple(int(i == dimension) for i in range(3)), scale)

UNIT_WORDS = {
    "kilogram": "kg", "gram": "g", "milligram": "mg", "microgram": "ug",
    "nanogram": "ng", "liter": "l", "milliliter": "ml", "microliter": "ul",
    "deciliter": "dl", "mole": "mol", "millimole": "mmol", "micromole": "umol",
}
ATOM = "(?:" + "|".join(sorted(UNITS, key=len, reverse=True)) + ")"
UNIT = rf"(?<![a-z]){ATOM}(?:\s*(?:/|\bper\b)\s*{ATOM})?(?![a-z])"
NUM = r"(?<![\w.])[-+]?(?:\d*\.\d+|\d+)(?:e[-+]?\d+)?(?!\d|\.\d)"


def norm(text):
    text = str(text).lower().replace("μ", "u").replace("µ", "u").replace("−", "-")
    text = text.replace("×", "*").replace("÷", "/").replace("_", " ").replace("litre", "liter")
    for word, name in UNIT_WORDS.items():
        text = re.sub(rf"\b{word}s?\b", name, text)
    return " ".join(text.split())


def unit_at(text):
    match = re.search(UNIT, text)
    if match:
        parts = re.split(r"\s*(?:/|\bper\b)\s*", match.group())
        if len(parts) == 1:
            return UNITS[parts[0]]
        return UNITS[parts[0]].combine(UNITS[parts[1]], -1)
    if re.search(r"\b(?:unitless|dimensionless|fraction)\b", text):
        return ONE
    return None


def field_text(fields, key):
    if isinstance(fields, dict):
        value = fields.get(key, "")
        if isinstance(value, dict):
            return norm(" ".join(str(value.get(k, "")) for k in ("name", "label", "description", "unit", "units")))
        return norm(value)
    return ""


class Quantity(NamedTuple):
    source: str
    unit: object = None


class Operation(NamedTuple):
    kind: str
    operand: object = None


class Conversion(NamedTuple):
    before: object
    after: Unit


class Program(NamedTuple):
    signal: Quantity
    factor: Quantity
    known_unit: object
    output_unit: object
    steps: tuple


SIG = r"(?:signals?|responses?|readings?|absorbance|intensit(?:y|ies)|counts?|sensor output|instrument output)"
KNOWN = r"(?:known(?:\s+(?:standard\s+)?(?:concentrations?|amounts?|levels?|values?|quantit(?:y|ies)))?|concentrations?|standard values?|reference values?|amounts?)"
FIT = r"\b(?:fits?|fitting|fitted|regress(?:ion|ed)?|calibrat(?:e|ed|ion)|least[- ]squares|ols|standard curve)\b"
BLANK = r"\b(?:blank|baseline|background|offset|tare)\b"
FACTOR = r"\b(?:factor|multiplier|divisor|dilution|volume|mass)\b"


def fit_direction(text):
    # The dependent variable is the left argument in "Y on X" and in Y = f(X).
    sides = ((SIG, KNOWN, "inverse"), (KNOWN, SIG, "direct"))
    found = set()
    for dep, ind, direction in sides:
        link = r"(?:on|against|vs\.?|versus|from|as (?:a |an? linear )?function of|as a linear function of|with respect to)"
        if re.search(rf"\b{dep}\b(?:\s*\([^)]*\))?\s+{link}\s+(?:the |standard |known standard |measured |instrument |raw )*{ind}\b", text):
            found.add(direction)
        if re.search(rf"\b{dep}\b\s*=\s*[^.;=]{{0,60}}?\b{ind}\b", text):
            found.add(direction)
        if re.search(rf"\b{dep}\b\s*(?:as |is |on |\()?\s*(?:the )?(?:dependent variable|response variable|y(?:-axis)?\b)", text):
            found.add(direction)
        if re.search(rf"\b{ind}\b\s*(?:as |is |on |\()?\s*(?:the )?(?:independent variable|predictor|x(?:-axis)?\b)", text):
            found.add(direction)
        if re.search(rf"\by\s*(?:=|is)\s*(?:the )?{dep}\b|\bx\s*(?:=|is)\s*(?:the )?{ind}\b", text):
            found.add(direction)
    if len(found) != 1:
        raise NeedInput("Which standard quantity is the fitted response and which is the predictor?")
    return found.pop()


def role_unit(text, role, field=""):
    # Only bind a unit next to its role. Units in a report clause belong to the output.
    descriptor = r"(?:sample |row |raw |measured |standard |known )*(?:mass|volume|concentration|amount|signal|value|factor)"
    link = rf"(?:\s+(?:column|field|values?|is|are|represents?|contains?|measures?|records?|the|a|an|as|in|of|given|expressed|measured|has|units?|per-row|aliquot|{descriptor}))*"
    matches = re.finditer(rf"\b{role}\b{link}\s*[(:=]?\s*({UNIT})", text)
    units = {unit_at(match.group(1)) for match in matches}
    described = unit_at(field)
    if described is not None:
        units.add(described)
    if len(units) > 1:
        raise NeedInput(f"Which input unit applies to {field or 'the stated quantity'}?")
    return next(iter(units), None)


def literal(match, unit=None):
    number = float(match)
    if not math.isfinite(number):
        raise NeedInput("What finite numerical value should be used?")
    return Quantity(repr(number), unit)


def blank_quantity(text, factor):
    if re.search(rf"(?:factor\b[^.;,]{{0,20}}(?:is|as|holds|contains) (?:the )?{BLANK}|{BLANK}[^.;,]{{0,18}}(?:is|from|in) (?:the )?(?:row )?factor)", text):
        return factor
    for pattern, expr in (
        (r"(?:first|initial) standard", "standards[0][0]"),
        (r"(?:mean|average) (?:of (?:the )?)?(?:standard signals|signals of the standards)", "mean(column(standards, 0))"),
        (r"(?:minimum|lowest) standard signal", "min(column(standards, 0))"),
    ):
        if re.search(rf"{BLANK}[^.;]{{0,45}}{pattern}|{pattern}[^.;]{{0,35}}{BLANK}", text):
            return Quantity(expr)
    patterns = (
        rf"{BLANK}(?:[- ](?:signal|reading|value|level|correction|offset|mass))?\s*\(?\s*(?:(?:is|was|fixed|set|of|at|equals?|with|=|:)\s*)*({NUM})",
        rf"({NUM})\s*(?:{UNIT}\s*)?(?:[a-z]+[- ]unit\s+)?{BLANK}",
        rf"\bsubtract(?:ing)?\s+({NUM})\b[^.;,]{{0,60}}?\bas (?:a |the )?{BLANK}",
    )
    values = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            tail = text[match.end(1):].lstrip()
            u = re.match(UNIT, tail)
            values.add(literal(match.group(1), unit_at(u.group()) if u else None))
    if len(values) != 1:
        raise NeedInput("What single blank value or reference should be used for the correction?")
    return values.pop()


# A controlled arithmetic vocabulary. Match each imperative only once.
VERB = re.compile(
    r"\b(?:(?P<sub>subtract(?:ing|ed)?|minus|less|deduct(?:ing)?|remove|blank[- ]correct(?:ed|ing)?)"
    r"|(?P<add>add(?:ing)?|plus)|(?P<mul>multipl(?:y(?:ing)?|ied|ication)|times|scale(?:d)?|scaling)"
    r"|(?P<div>divid(?:e|ed|ing)|over|normaliz(?:e|ed|ing))"
    r"|(?P<apply>apply(?:ing)?|applied|correct(?:ed|ing)? for|adjust(?:ed)? for|restore)"
    r"|(?P<round>round(?:ed|ing)?))\b|(?P<symbol>[*/])"
)


def parse_operand(segment, quantities, blank):
    # The object after by/to is the operand ("divide the value by its row factor").
    segment = re.split(r"\bby\b", segment, maxsplit=1)[-1]
    segment = re.sub(r"^\s*(?:the |a |an |its |each |corresponding |per[- ]row |row[- ]specific |sample[- ]specific )*", "", segment)
    if blank is not None and re.search(BLANK, segment):
        return blank
    number = re.search(NUM, segment)
    token = re.search(FACTOR, segment)
    if number and (not token or number.start() < token.start() or re.match(r"\s*(?:of|=|is|:)\s*$", segment[token.end():number.start()])):
        remaining = segment[number.end():].lstrip()
        u = re.match(UNIT, remaining)
        return literal(number.group(), unit_at(u.group()) if u else None)
    if token:
        if token.group() not in quantities:
            raise NeedInput(f"What value and unit supply the {token.group()}?")
        return quantities[token.group()]
    if number:
        return literal(number.group())
    raise NeedInput("What number or row field should be used for the stated arithmetic operation?")


def bind_quantities(text, factor, field):
    quantities = dict.fromkeys(("factor", "dilution", "multiplier", "divisor"), factor)
    for role, dim in (("mass", 0), ("volume", 1)):
        if (role in field or (factor.unit and factor.unit.dimensions[dim] == 1)
                or re.search(rf"\bfactor\b\s*(?:(?:column |field )?(?:is|as|represents|contains|gives|holds)\s+)?(?:the |a |sample |aliquot )*{role}\b|\b{role} (?:as|in) (?:the )?(?:row )?factor\b", text)):
            quantities[role] = factor
        pattern = rf"\b{role}\s*(?:(?:of|was|is|=|:)\s*)+({NUM})\s*({UNIT})|({NUM})\s*({UNIT})\s+(?:(?:sample|aliquot|total) )?{role}\b"
        for match in re.finditer(pattern, text):
            num, u = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
            q = literal(num, unit_at(u))
            if role in quantities and quantities[role] != q:
                raise NeedInput(f"Which {role} should be used for this sample?")
            quantities[role] = q
    return quantities


def formula_steps(clause, quantities, blank):
    # Recognize explicit scalar formulae as complete expressions. A single
    # accumulator can represent a left-associated chain with literal/field operands.
    match = re.fullmatch(
        r"\s*(?:(?:report|return|compute|calculate)\s+|(?:output|result|value)\s*=\s*)?"
        r"([\w\s().+*/-]+?)(?:\s+in\s+" + UNIT + r")?\s*", clause)
    if not match or not re.search(r"[+*/-]", match.group(1)):
        return None
    formula = match.group(1).strip()
    if not re.match(r"^\(*\s*signal\b", formula):
        return None
    try:
        node = ast.parse(formula, mode="eval").body
    except (ValueError, SyntaxError, RecursionError):
        # Text may also begin with a signal declaration, e.g. "signal is ...".
        if re.match(r"^signal\s+(?:is|in|measures|represents)\b", formula):
            return None
        raise NeedInput("Please write the scalar formula with explicit arithmetic operators.") from None
    steps = []
    operators = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div"}
    while isinstance(node, ast.BinOp) and type(node.op) in operators:
        term = node.right
        if isinstance(term, ast.Name) and term.id in quantities:
            operand = quantities[term.id]
        elif isinstance(term, ast.Name) and term.id == "blank" and blank:
            operand = blank
        elif isinstance(term, ast.Constant) and type(term.value) in (int, float):
            operand = literal(str(term.value))
        else:
            raise NeedInput("Please express this calculation as ordered operations on the signal using stated operands.")
        steps.append(Operation(operators[type(node.op)], operand))
        node = node.left
    if not isinstance(node, ast.Name) or node.id != "signal":
        raise NeedInput("What sequence of scalar arithmetic operations should be applied to the signal?")
    return list(reversed(steps))


def clauses(text):
    text = re.sub(r"\bvs\.\s+", "vs ", text)
    for part in re.split(r"(?<!\d)\.(?!\d)|(?<=\d)\.(?!\d)|[;\n]", text):
        # "After subtracting A, multiply by B" and "multiply by B after subtracting A".
        initial = re.match(r"\s*(after|before)\s+(.+?),\s*(.+)", part)
        if initial:
            _, first, last = initial.groups()
            yield from ((first, last) if initial.group(1) == "after" else (last, first))
        else:
            halves = re.split(r"\s+after\s+(?=(?:subtract|multipl|divid|add|blank[- ]correct|fit|apply))", part, maxsplit=1)
            yield from reversed(halves)


def compile_protocol(request):
    if not isinstance(request, dict) or not isinstance(request.get("protocol"), str):
        raise NeedInput("Please provide the numerical protocol for one observation.")
    text = norm(request["protocol"])
    fields = request.get("fields", {})
    sfield = field_text(fields, "signal")
    ffield = field_text(fields, "factor")
    # Recognize explicitly named columns even when they do not use canonical parameter names.
    for field, role in ((sfield, "signal"), (ffield, "factor")):
        if field and field not in {"mass", "volume", "concentration", "dilution", "blank", "factor", "signal"}:
            text = re.sub(rf"\b{re.escape(field)}\b", role, text)
    if not text or len(text) > 8192 or re.search(r"\b(?:unspecified|unknown (?:blank|direction|unit|volume)|quadratic|nonlinear|weighted|piecewise|median|logarithm\w*|log10|exponential|squar(?:e|ing|ed)|square root|sine|cosine|log|reciprocal|absolute value|through (?:the )?origin|zero intercept|intercept[- ]free|interpolat\w*|either|possibly|optionally|unless|instead of|depending on|otherwise)\b", text):
        raise NeedInput("Please specify a single supported calculation, including the fit and correction assumptions.")
    target_text = norm(request.get("unit", ""))
    if re.search(r"[/]|\bper\b", target_text) and not re.fullmatch(UNIT, target_text):
        raise NeedInput("Please specify the output as a supported mass, volume, amount, or ratio of these units.")
    target = unit_at(target_text)
    for match in re.finditer(rf"\b(?:report|express)\b[^.;,]{{0,50}}?\b(?:in|as)\s+({UNIT})", text):
        if target and unit_at(match.group(1)) != target:
            raise NeedInput("Which reporting unit should the function return?")
    signal_unit = role_unit(text, SIG, sfield)
    factor_unit = role_unit(text, r"factor", ffield)
    known_unit = role_unit(text, KNOWN)
    text = re.sub(r"\b(?:no|without) (?:a |any )?(?:calibration|fit|regression)(?: (?:is )?(?:used|required|needed))?\b", "", text)
    is_fit = bool(re.search(FIT, text))
    direction = fit_direction(text) if is_fit else None
    if not signal_unit and not is_fit:
        for role in ("mass", "volume", "concentration"):
            if role in sfield or re.search(rf"(?:signal\s+(?:is|as|represents|gives|records)\s+(?:the |a )?{role}|{role}\s+(?:in|as)\s+(?:the )?signal)", text):
                signal_unit = role_unit(text, role)
    if not factor_unit:
        for role in ("mass", "volume"):
            if role in ffield or re.search(rf"factor\s+(?:is|as|represents|gives|records)\s+(?:the |a )?{role}", text):
                factor_unit = role_unit(text, role)
    factor = Quantity("factor", factor_unit)
    quantities = bind_quantities(text, factor, ffield)
    if target and not is_fit and ("volume" in quantities or "mass" in quantities):
        for role in ("volume", "mass"):
            if quantities.get(role) == factor and factor_unit is None:
                raise NeedInput(f"In which unit is the row {role} recorded?")
    if re.search(rf"(?:subtract|deduct)\b[^.;,]*?\bfrom\b[^.;,]*?\bstandards\b|blank[- ]correct (?:all |the |both )*standards", text):
        raise NeedInput("Please specify a calibration using the supplied standard pairs or provide pre-corrected standards.")
    blank = blank_quantity(text, factor) if re.search(BLANK, text) else None
    steps = []
    fit_added = False
    blank_applied = False
    ignores_factor = bool(re.search(r"\b(?:ignore|omit|skip|do not (?:use|apply)) (?:the )?(?:row )?(?:factor|dilution)|\bfactor (?:is )?(?:unused|ignored|unity)", text))
    for clause in clauses(text):
        formula = formula_steps(clause, quantities, blank) if not is_fit else None
        if formula:
            steps.extend(formula)
            blank_applied |= any(op.kind == "sub" and op.operand == blank for op in formula)
            continue
        fm = re.search(FIT, clause) if not fit_added and is_fit else None
        # Mask unit slashes so they never become arithmetic, preserving positions.
        masked = re.sub(UNIT, lambda m: " " * len(m.group()), clause)
        if fm:
            # An equation in a fitted calibration declares direction, not scalar arithmetic.
            masked = re.sub(r"\b(?:signal|response|known|concentration)\s*=[^,;]*?(?=,|\bthen\b|\band\b|$)", lambda m: " " * len(m.group()), masked)
        verbs = list(VERB.finditer(masked))
        events = []
        for change in re.finditer(rf"\bconvert\b[^.;,]{{0,60}}?\b(?:to|into)\s+({UNIT})", clause):
            before = re.search(rf"\bfrom\s+({UNIT})", change.group())
            events.append((change.start(), Operation("convert", Conversion(
                unit_at(before.group(1)) if before else None, unit_at(change.group(1))))))
        if fm:
            events.append((fm.start(), Operation(direction)))
            fit_added = True
        for i, verb in enumerate(verbs):
            kind = verb.lastgroup
            if kind == "symbol":
                kind = "mul" if verb.group() == "*" else "div"
            end = verbs[i + 1].start() if i + 1 < len(verbs) else len(clause)
            segment = re.split(r"\b(?:then|and then|before|report|express|convert)\b|[,]", clause[verb.end():end], maxsplit=1)[0]
            if re.search(r"\b(?:do not|never|without|not)\s*$", clause[:verb.start()]):
                if re.search(r"\bfactor\b", segment):
                    ignores_factor = True
                    continue
                raise NeedInput("Which positive sequence of operations should the function perform?")
            if kind == "round":
                match = re.search(r"\b(\d+) decimal (?:places?|digits?)", segment)
                if not match or int(match.group(1)) > 12:
                    raise NeedInput("How many decimal places should the result retain (0 to 12)?")
                operand = literal(match.group(1))
            elif kind == "apply":
                if blank is not None and re.search(BLANK, segment):
                    kind, operand = "sub", blank
                elif re.search(r"factor|dilution|multiplier", segment):
                    kind = "div" if "divisor" in ffield or re.search(r"\bfactor is (?:a |the )?divisor\b", text) else "mul"
                    operand = factor
                elif re.search(r"calibration|fit|curve|equation", segment):
                    continue
                else:
                    raise NeedInput("Which correction should be applied, and how?")
            elif kind == "sub" and blank is not None and (re.search(BLANK, segment) or "blank" in verb.group()):
                kind, operand = "sub", blank
            else:
                operand = parse_operand(segment, quantities, blank)
            if kind == "sub" and re.search(r"\b(?:signal|reading|result)\s+from\b", segment):
                raise NeedInput("Please specify the subtraction as an ordered calculation.")
            if operand == blank and kind == "sub":
                blank_applied = True
            events.append((verb.start(), Operation(kind, operand)))
        steps.extend(op for _, op in sorted(events, key=lambda entry: entry[0]))

    if blank is not None and not blank_applied:
        raise NeedInput("At which step and from which quantity should the blank be subtracted?")
    used_factor = any(op.operand == factor for op in steps)
    if not used_factor and not ignores_factor:
        # Physical ratios can also be specified by naming the two quantities and output.
        if (not steps and signal_unit and factor_unit and target
                and signal_unit.combine(factor_unit, -1).dimensions == target.dimensions
                and factor_unit.dimensions != ONE.dimensions):
            steps.append(Operation("div", factor))
        elif re.search(r"\b(?:dilution[- ]correct(?:ed|ion)?|back[- ]calculate.{0,20}dilution)\b", text):
            steps.append(Operation("mul", factor))
        elif re.search(r"\bfactor\b", text) and not re.search(r"factor (?:is )?(?:always )?1\b", text):
            raise NeedInput("How and at which step should the row factor enter the calculation?")
    if len(steps) > 16:
        raise NeedInput("Can the protocol be reduced to at most 16 scalar operations?")
    if not steps and not re.search(r"\b(?:return|report|convert|use)\s+(?:the |raw |measured )*signal\b", text):
        raise NeedInput("Which numerical operations map the signal and row factor to the output?")
    if target_text and target is None and (signal_unit or known_unit or factor_unit):
        raise NeedInput(f"How should the physical measurement be expressed in {target_text}?")
    return Program(Quantity("signal", signal_unit), factor, known_unit, target, tuple(steps))


def emit(program):
    lines = ["def analyze(standards, signal, factor):"]
    expr, unit = program.signal
    numeric_scales = []

    def conversion_scale(before, after):
        scale = before.conversion(after)
        if scale != 1 and any(math.isclose(scale, previous, rel_tol=1e-12) for previous in numeric_scales):
            raise NeedInput("Does the stated numerical multiplier already include the unit conversion?")
        return scale

    for i, op in enumerate(program.steps):
        if op.kind == "convert":
            before, after = op.operand
            if before and unit and before != unit:
                raise NeedInput("Which unit applies immediately before the conversion?")
            if not (unit or before):
                raise NeedInput("What is the source unit for the conversion?")
            value = f"{expr} * {conversion_scale(unit or before, after)!r}"
            numeric_scales.clear()
            unit = after
        elif op.kind in {"direct", "inverse"}:
            x, y = (0, 1) if op.kind == "direct" else (1, 0)
            lines.extend((f"    x = column(standards, {x})", f"    y = column(standards, {y})",
                          "    m = slope(x, y)", "    b = intercept(x, y)"))
            value = f"m * {expr} + b" if op.kind == "direct" else f"({expr} - b) / m"
            unit = program.known_unit
            numeric_scales.clear()
        else:
            rhs, other = op.operand
            if op.kind in {"sub", "add"}:
                if unit and other:
                    scale = other.conversion(unit)
                    if scale != 1:
                        rhs = f"({rhs} * {scale!r})"
                elif other:
                    unit = other
            if op.kind in {"mul", "div"} and other:
                if unit is None and other.dimensions != ONE.dimensions:
                    raise NeedInput("What is the input unit before the mass or volume operation?")
                if unit:
                    unit = unit.combine(other, 1 if op.kind == "mul" else -1)
            if op.kind == "round":
                value = f"round({expr}, {rhs})"
            else:
                symbol = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[op.kind]
                if op.kind == "div" and rhs in {"0.0", "-0.0"}:
                    raise NeedInput("What nonzero divisor should be used?")
                if other is None and op.kind in {"div", "mul"} and re.fullmatch(NUM, rhs):
                    numeric_scales.append(float(rhs) if op.kind == "mul" else 1 / float(rhs))
                value = f"{expr} {symbol} {rhs}"
        expr = f"v{i}"
        lines.append(f"    {expr} = {value}")
    if unit and program.output_unit:
        scale = conversion_scale(unit, program.output_unit)
        if scale != 1:
            expr = f"{expr} * {scale!r}"
    lines.append(f"    return {expr}")
    return "\n".join(lines) + "\n"


def solve(request):
    try:
        return {"source": emit(compile_protocol(request))}
    except NeedInput as exc:
        return {"needs_input": str(exc)}
