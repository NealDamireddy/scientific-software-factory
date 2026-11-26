"""Offline authoring from a controlled vocabulary of numerical methods."""

import math
import re


class Clarify(ValueError):
    """A template parameter cannot be bound from the request."""


def clean(value):
    value = value.casefold().replace("µ", "u").replace("μ", "u")
    value = value.translate(str.maketrans({"×": "*", "÷": "/", "−": "-", "²": "^2",
                                           "’": "'", "–": "-", "_": " "}))
    value = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", value)
    value = re.sub(r"\b(kilo|milli|micro|nano)?gram(?:me)?s?\b",
                   lambda m: {None: "g", "kilo": "kg", "milli": "mg",
                              "micro": "ug", "nano": "ng"}[m[1]], value)
    value = re.sub(r"\b(milli|micro)?lit(?:er|re)s?\b",
                   lambda m: {None: "l", "milli": "ml", "micro": "ul"}[m[1]], value)
    return " ".join(value.split()).strip()


MASS = {"kg": 3, "g": 0, "mg": -3, "ug": -6, "ng": -9}
VOLUME = {"l": 0, "ml": -3, "ul": -6}
M = "(?:kg|mg|ug|ng|g)"
V = "(?:ml|ul|l)"
RATIO = rf"\b({M})\s*(?:/|\bper\b)\s*({V})\b"
NUMBER = r"(?<![\w.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?(?!\w|\.\d)"
# Unrecognized terms can describe an additional operation. Only descriptions in
# this vocabulary reach the calculation templates.
VOCAB = set("""
a all an and are as at be before by each for from in including into is it its of on
after per prior following that the their them then this to use used using with was
apply applying adjust adjusting correct correcting corrected undo multiply multiplied
multiplying scale scaled scaling times divide divided dividing over subtract subtracting
subtracted minus remove removing compute calculate find determine obtain combine
result results resulting return report express output convert conversion units unit
linear line straight ordinary least squares ols regression regress regressing calibration
calibrate calibrated calibrating curve fit fits fitted fitting model standard standards
batch pair pairs point points x y m b a slope intercept gradient axes axis dependent
independent predictor variable function vs versus against predict predicts prediction
predicted estimate estimated inferred infer invert inverting inversion inverse
solve back calculate equation unknowns raw target value values sample samples each row
rows measurement measurements instrument detector measured known reference assigned
certified true concentrations concentration amount amounts level levels mass masses
weight volume volumes ratio density final original diluted undiluted dilution
factor factors multiplier divisor correction multiplication division scaling
signal signals reading readings response responses absorbance absorbances intensity
intensities count counts voltage voltages blank blanks background baseline offset
mean average first initial all stored holds contains represents provided supplies
field fields column columns table data recorded given directly numerical numeric
aliquot recovered effective observation observations specimen specimens corresponding
respectively calculated
units arbitrary au dimensionless v mv uv volt volts millivolt millivolts ppm ppb
kg g mg ug ng l ml ul
""".split())


def check_vocabulary(text, unit):
    words = set(re.findall(r"[a-z]+", re.sub(NUMBER, " ", text)))
    unknown = sorted(words - VOCAB - set(re.findall(r"[a-z]+", unit)))
    if unknown:
        raise Clarify(f"How does '{unknown[0]}' affect the calculation? State its arithmetic meaning.")


def scales(text):
    return {MASS[m] - VOLUME[v] for m, v in re.findall(RATIO, text)}


SIMPLE_UNITS = {
    **{k: ("mass", v) for k, v in MASS.items()},
    **{k: ("volume", v) for k, v in VOLUME.items()},
    **dict.fromkeys(("v", "volt", "volts"), ("voltage", 0)),
    **dict.fromkeys(("mv", "millivolt", "millivolts"), ("voltage", -3)),
    "uv": ("voltage", -6), "count": ("counts", 0), "counts": ("counts", 0),
    "au": ("arbitrary", 0),
}
UNIT_EXPR = RATIO + r"|\b(?:" + "|".join(SIMPLE_UNITS) + r")\b"


def measurements(text):
    found = {("concentration", scale) for scale in scales(text)}
    return found | {SIMPLE_UNITS[word] for word in unary_unit(text, SIMPLE_UNITS)}


def blank_units(signal, blank, unit):
    # A bare blank value uses the signal's scale. With no signal unit, use the
    # declared blank or result scale. Different physical dimensions need input.
    signal_units, blank_units, output_units = map(measurements, (signal, blank, unit))
    if any(len(s) > 1 for s in (signal_units, blank_units, output_units)):
        raise Clarify("Specify one measurement unit each for the signal, blank, and result.")
    raw = signal_units or blank_units or output_units
    if not raw:
        return 0, 0
    kind, scale = next(iter(raw))
    if not output_units or any(k != kind for k, _ in blank_units | output_units):
        raise Clarify("How should the blank, signal, and requested output units be reconciled?")
    blank_scale = next(iter(blank_units))[1] if blank_units else scale
    return blank_scale - scale, scale - next(iter(output_units))[1]


def field_text(fields, key):
    value = fields.get(key) if isinstance(fields, dict) else None
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return clean(" ".join(str(value[k]) for k in
                              ("name", "label", "description", "role", "unit", "units")
                              if isinstance(value.get(k), str)))
    if isinstance(fields, (tuple, list)):
        for field in fields:
            if field == key:
                return key
            if isinstance(field, dict) and field.get("name") == key:
                return field_text({key: field}, key)
    return ""


def unary_unit(text, symbols):
    text = re.sub(RATIO, " ", text)
    return set(re.findall(r"\b(?:" + "|".join(symbols) + r")\b", text))


def description(text, role):
    # Accept declarations such as "signal is mass in mg" and "volume (factor)".
    return " ".join(re.findall(
        rf"\b{role}\s*(?:\bis\b|\bcontains\b|\brepresents\b|\bstores\b|=|:|\()\s*"
        r"([^.;,()]{1,56}?)(?=\s+(?:and|then|by|from|versus|against)\b|[.,;()]|$)", text))


def physical_kinds(label):
    result = set()
    if unary_unit(label, MASS) or re.search(r"\b(?:mass|weight)\b", label):
        result.add("mass")
    if unary_unit(label, VOLUME) or re.search(r"\bvolume\b", label):
        result.add("volume")
    if re.search(r"\b(?:time|duration|seconds?|temperature|kelvin|celsius|pressure|voltage|counts?)\b", label):
        result.add("other")
    return result


def operand_unit(label, protocol, units):
    evidence = unary_unit(label, units) | unary_unit(protocol, units)
    if len(evidence) != 1:
        raise Clarify("What single unit is used for each input mass and volume?")
    return evidence.pop()


def convert(expr, exponent):
    if not exponent:
        return expr
    op = "*" if exponent > 0 else "/"
    return f"({expr}) {op} {10 ** abs(exponent)}"


def mass_per_volume(text, sig, fac, output):
    target = scales(output)
    if len(target) != 1:
        raise Clarify("Which mass-per-volume unit should the result use?")
    a, b = physical_kinds(sig), physical_kinds(fac)
    # A literal field assignment takes precedence over guessing an input order.
    if a == {"mass"} and b == {"volume"}:
        numerator, denominator, mass, volume = "signal", "factor", sig, fac
    elif b == {"mass"} and a == {"volume"}:
        numerator, denominator, mass, volume = "factor", "signal", fac, sig
    else:
        raise Clarify("Which field supplies mass and which supplies volume, and in what units?")
    if not re.search(r"\b(?:divid\w*|over|per|ratio|concentration|density)\b|/", text):
        raise Clarify("How should the input mass and volume be combined?")
    if (re.search(r"\bvolume\b[^.;]{0,24}\b(?:by|over|per)\s+(?:the )?mass\b|volume\s*/\s*mass", text)
            or re.search(rf"\b{denominator}\s*(?:/|divided by|over)\s*(?:the )?{numerator}\b", text)
            or re.search(r"\b(?:multiply|multiplied|times|plus|minus|subtract|blank)\b|[+*]", text)):
        raise Clarify("Please specify the mass divided by volume calculation and any extra steps.")
    m = operand_unit(mass, text, MASS)
    v = operand_unit(volume, text, VOLUME)
    return convert(f"{numerator} / {denominator}", MASS[m] - VOLUME[v] - target.pop())


S = r"(?:signals?|readings?|responses?|absorbances?|intensit(?:y|ies)|counts?|voltages?)"
K = r"(?:(?:known|reference|assigned|certified|true)(?: standard)?(?: values?| levels?| amounts?| masses?| concentrations?)?|concentrations?|amounts?)"


def axes(text):
    text = re.sub(r"\bas (?:the |a )?response\b", "as dependent variable", text)
    text = re.sub(r"\bas (?:the |a )?predictor\b", "as independent variable", text)
    text = re.sub(r"(?:\bin\s+)?\(?\s*" + RATIO + r"\s*\)?", " ", text)
    text = " ".join(text.split())
    text = re.sub(rf"\b(?:measured |instrument |standard |detector )?{S}\b", "S", text)
    text = re.sub(rf"\b(?:standard )?{K}\b", "K", text)
    pair = r"\b([SK])\s*(?:\([^()]*\)\s*)?(?:on|against|vs\.?|versus|as (?:a |an )?(?:linear )?function of|as a function of)\s+(?:the )?([SK])\b"
    dependent = {a for a, b in re.findall(pair, text) if a != b}
    for y, x in (("S", "K"), ("K", "S")):
        # Direction is also specified by an equation, labelled axes, or a fit verb.
        if (re.search(rf"\b{y}\s*=\s*[^.;,=]{{0,65}}?\b{x}\b", text)
                or re.search(rf"\b(?:dependent variable|y(?: axis)?)\s*(?:=|is|:|as)\s*{y}\b", text)
                or re.search(rf"\b{y}\s+(?:as|is) (?:the )?(?:dependent variable|y(?: axis)?)\b", text)
                or re.search(rf"\b{x}\s+(?:as|is) (?:the )?(?:independent variable|x(?: axis)?)\b", text)
                or re.search(rf"\b(?:x(?: axis)?|independent variable)\s*(?:=|is|:)\s*{x}\b", text)
                or re.search(rf"\b{y}\s*\(y\)|\b{x}\s*\(x\)", text)
                or re.search(rf"\b(?:regress|fit|model)\s+(?:the )?{y}\s+from\s+(?:the )?{x}\b", text)):
            dependent.add(y)
    inverse = bool(re.search(r"\b(?:invert|inverting|inversion|back calculate|solve (?:it |the (?:line|equation) )?for K)\b", text))
    if inverse:
        dependent.add("S")
    if len(dependent) != 1:
        raise Clarify("Which variable is the fitted response, signal or known value?")
    return dependent.pop()


def regression(text):
    direction = axes(text)
    lines = ["signals = column(standards, 0)", "known = column(standards, 1)"]
    if direction == "K":
        lines.append("value = slope(signals, known) * signal + intercept(signals, known)")
    else:
        lines.append("value = (signal - intercept(known, signals)) / slope(known, signals)")
    return lines


def calibration_scale(text, unit):
    # Bind units to the known axis or to an explicit "convert from" phrase.
    prefix = rf"(?:\b{K}\b\s*(?:(?:is |are )?in\s+|\(\s*)?|\bconvert\s+(?:from\s+)?)"
    found = set()
    for match in re.finditer(prefix + rf"(?P<u>{UNIT_EXPR})", text):
        found.update(measurements(match["u"]))
    if not found:
        if "convert" in text:
            raise Clarify("Which unit do the known standard values use before conversion?")
        return 0
    output = measurements(unit)
    if len(found) == len(output) == 1:
        kind, source_scale = found.pop()
        output_kind, target_scale = output.pop()
        if kind == output_kind:
            return source_scale - target_scale
    raise Clarify("Specify a single known-standard unit and compatible output unit.")


F = r"(?:(?:per row|row|sample|dilution|scale|scaling|correction|multiplication|division|volume) )*(?:factor|multiplier|divisor)|dilution factor|dilution"
REF = rf"(?:the |its |each |a |an )?(?:{F})\b"


def factor_step(text, fac):
    ops = []
    for op, word in (("*", r"multipl(?:y|ied|ying)|scal(?:e|ed|ing)"), ("/", r"divid(?:e|ed|ing)")):
        for m in re.finditer(rf"\b(?:{word})\b[^;.!?]{{0,65}}?\bby\s+{REF}", text):
            ops.append((m.start(), op))
        for m in re.finditer(rf"(?:{re.escape(op)}|\b{'times' if op == '*' else 'over'}\b)\s*{REF}", text):
            ops.append((m.start(), op))
    for m in re.finditer(rf"\b(?:apply|applying|correct(?:ing)? for|adjust(?:ing)? for|undo)\s+{REF}", text):
        if "dilution" in m[0] or re.search(r"\b(?:dilution|multiplier)\b", fac):
            ops.append((m.start(), "*"))
        else:
            raise Clarify("Should the row factor multiply or divide the value?")
    if len(ops) > 1:
        raise Clarify("Specify one operation using the row factor.")
    return ops[0] if ops else None


def blank_subtraction(text, fac):
    if re.search(r"\bsubtract\s+(?:the |sample )*(?:raw )?(?:signal|reading)\b[^.;]*\bfrom\b", text):
        raise Clarify("Which value should be subtracted from which?")
    if not re.search(r"\b(?:subtract\w*|minus|remov\w*|blank correct\w*|correct\w* for (?:the )?blank)\b|\s-\s", text):
        raise Clarify("How should the blank be applied to the measurement?")
    choices = []
    blank_unit = ""
    literal = rf"(?:\b(?:blank|background|baseline|offset)(?:\s+(?:signal|reading|value|offset|level))?\s*(?:of|=|:|is|was|at)?\s*({NUMBER})|({NUMBER})\s*(?:[a-z]+\s+)?(?:blank|background|baseline)\b)"
    for match in re.finditer(literal, text):
        number = float(match[1] or match[2])
        if not math.isfinite(number):
            raise Clarify("Supply a finite blank value.")
        choices.append(repr(number))
        end = match.end(1) if match[1] else match.end(2)
        unit = re.match(r"\s*[-(]?\s*(" + RATIO + r"|[a-z]+)\b", text[end:])
        if unit and measurements(unit[1]):
            blank_unit = unit[1]
    first = r"(?:first|initial) (?:calibration )?(?:standard|row)|standard\s*\[0\]|standards\[0\]\[0\]"
    if re.search(first, text):
        if re.search(r"\b(?:first|initial)\s+(?:two|three|\d+)|\b(?:known value|concentration) of the first", text):
            raise Clarify("Which standard signals define the blank?")
        choices.append("standards[0][0]")
    elif re.search(r"\b(?:mean|average)\b", text) and re.search(r"\b(?:all (?:the )?standards?|standards? (?:are|as) blanks?)\b", text):
        if re.search(r"\b(?:only|where|subset|zero)\b", text):
            raise Clarify("Which available rows contain the blank readings?")
        choices.append("mean(column(standards, 0))")
    if re.search(r"\b(?:blank|background|baseline)\b", fac) or re.search(r"\bsubtract (?:the )?(?:row )?factor\b", text):
        choices.append("factor")
        blank_unit = fac
    if len(set(choices)) != 1:
        raise Clarify("Specify the blank value, or identify the field or standard row providing it.")
    return choices[0], blank_unit


def scale_first(text, scale, subtract):
    ordering = list(re.finditer(r"\b(before|after|prior to|following)\b", text))
    if len(ordering) > 1:
        raise Clarify("State the blank and scaling steps in execution order.")
    if not ordering:
        return scale < subtract
    relation = ordering[0]
    if relation.start() > max(scale, subtract):
        raise Clarify("Which operation should run first, blank subtraction or scaling?")
    prefix = relation.start() < min(scale, subtract)
    reverse = prefix == (relation[1] in ("before", "prior to"))
    return (scale < subtract) != reverse


def program(lines, expr):
    return {"source": "def analyze(standards, signal, factor):\n" +
            "".join("    " + line + "\n" for line in lines) + "    return " + expr + "\n"}


def author(request):
    if not isinstance(request, dict):
        raise Clarify("Supply a protocol, signal and factor fields, and the output unit.")
    protocol, unit = request.get("protocol"), request.get("unit")
    if not isinstance(protocol, str) or not isinstance(unit, str) or not unit.strip():
        raise Clarify("Supply the numerical procedure and the requested output unit.")
    text, unit = clean(protocol), clean(unit)
    fields = request.get("fields")
    sig, fac = field_text(fields, "signal"), field_text(fields, "factor")
    if not sig or not fac:
        raise Clarify("Identify the signal and factor fields for this procedure.")
    sig += " " + description(text, "signal")
    fac += " " + description(text, "factor")
    if not text or "?" in text:
        raise Clarify("Specify one supported calculation, including its operands and operation order.")
    check_vocabulary(text, unit)
    # Output declarations in the protocol and metadata must agree.
    label = r"\b(?:report|return|express|output|convert)\s+(?:[^.;]{0,45}?\b(?:in|as|to)\s+)?"
    targets = re.finditer(label + "(" + UNIT_EXPR + ")", text)
    if any(measurements(m[1]) != measurements(unit) for m in targets):
        raise Clarify("Which final unit should be used? The protocol and output unit differ.")
    method_fit = bool(re.search(r"\b(?:fit|fitted|fitting|regress\w*|calibration (?!standards?\b)\w+|ols|least squares|slope|intercept|standard curve)\b", text))
    blank = bool(re.search(r"\b(?:blanks?|background|baseline)\b|\bsubtract\w* (?:the )?first standard", text))
    if not blank and re.search(NUMBER, text):
        raise Clarify("Specify the role of each numerical constant in the calculation.")
    kinds = physical_kinds(sig) | physical_kinds(fac)
    if {"mass", "volume"} <= kinds and not method_fit and not blank:
        return program([], mass_per_volume(text, sig, fac, unit))
    if method_fit and blank:
        raise Clarify("Specify whether the blank applies to standards, samples, or calibrated results.")
    if not (method_fit or blank):
        raise Clarify("Specify the calibration, mass and volume, or blank-correction calculation.")
    op = factor_step(text, fac)
    if not op and re.search(r"\b(?:multiply|divide|multiplied|divided|times|apply the factor|dilution)\b", text):
        raise Clarify("Identify the operands and how the row factor should be applied.")
    if re.search(r"\b(?:multiply|divide|scale)\b[^.;]*?\bby\s+(?:a |the )?(?:constant|[0-9])", text):
        raise Clarify("Specify how the extra numerical scale enters the calculation.")
    exponent = 0
    if method_fit:
        lines = regression(text)
        if re.search(r"\b(?:subtract\w*|minus|remov\w*|mean|average)\b", text):
            raise Clarify("Specify the extra adjustment separately from fitting and inverting the line.")
        preprocessing = (r"\b(?:multipl\w*|divid\w*|scal\w*)\s+(?:the )?(?:raw |sample |measured )*"
                         r"(?:signal|reading)\b|\bbefore\s+(?:calibrat\w*|invert\w*|predict\w*|fitt\w*)")
        if op and re.search(preprocessing, text):
            raise Clarify("Specify the signal preprocessing separately from scaling the calibrated result.")
        exponent = calibration_scale(text, unit)
        expr = "value"
    else:
        term, blank_unit = blank_subtraction(text, fac)
        literals = re.findall(NUMBER, text.replace("standards[0][0]", "").replace("standard[0]", ""))
        if literals and (len(literals) != 1 or repr(float(literals[0])) != term):
            raise Clarify("Identify a single blank and specify the role of any other constants.")
        blank_scale, exponent = blank_units(sig, blank_unit, unit)
        if op and term == "factor":
            raise Clarify("Which field supplies the blank and which supplies the independent scale?")
        term = convert(term, blank_scale)
        lines = []
        expr = f"(signal - {term})"
        if op:
            subtract = re.search(r"\b(?:subtract\w*|minus|remov\w*|blank correct\w*)\b", text)
            if not subtract:
                raise Clarify("State the blank and scaling steps in execution order.")
            if scale_first(text, op[0], subtract.start()):
                return program([], convert(f"(signal {op[1]} factor) - {term}", exponent))
    if op:
        expr = f"{expr} {op[1]} factor"
    return program(lines, convert(expr, exponent))


def solve(request):
    try:
        return author(request)
    except Clarify as question:
        return {"needs_input": str(question)}
