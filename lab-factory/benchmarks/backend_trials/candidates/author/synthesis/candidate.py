"""Bounded synthesis of numerical programs for anonymous tabular measurements."""

from fractions import Fraction
from itertools import permutations, product
import re


class Clarify(ValueError):
    """A constraint is missing or outside the finite program grammar."""


def _text(value):
    if isinstance(value, dict):
        value = " ".join(str(value.get(k, "")) for k in ("name", "label", "description", "unit", "units"))
    if not isinstance(value, str):
        return ""
    value = value.casefold().replace("μ", "u").replace("µ", "u").replace("×", "*")
    value = value.replace("−", "-").replace("÷", "/").replace("_", " ").replace("’", "'")
    return re.sub(r"\s+", " ", value).strip()


def _units_text(value):
    for pattern, short in (
        (r"microgram(?:me)?s?|mcg", "ug"), (r"milligram(?:me)?s?", "mg"),
        (r"kilogram(?:me)?s?", "kg"), (r"nanogram(?:me)?s?", "ng"),
        (r"gram(?:me)?s?", "g"), (r"microlit(?:er|re)s?", "ul"),
        (r"millilit(?:er|re)s?", "ml"), (r"lit(?:er|re)s?", "l"),
    ):
        value = re.sub(r"\b(?:" + pattern + r")\b", short, value)
    return re.sub(r"\s+per\s+|\s*/\s*", "/", value)


_SCALE = {
    "ng": ("mass", Fraction(1, 10**9)), "ug": ("mass", Fraction(1, 10**6)),
    "mg": ("mass", Fraction(1, 1000)), "g": ("mass", Fraction(1)), "kg": ("mass", Fraction(1000)),
    "ul": ("volume", Fraction(1, 10**6)), "ml": ("volume", Fraction(1, 1000)), "l": ("volume", Fraction(1)),
    "mmol": ("amount", Fraction(1, 1000)), "umol": ("amount", Fraction(1, 10**6)),
    "mol": ("amount", Fraction(1)),
}
_SYMBOL = r"(?:mmol|umol|mol|kg|mg|ug|ng|ml|ul|g|l)"
_UNIT = re.compile(r"\b" + _SYMBOL + r"(?:/" + _SYMBOL + r")?\b")


def _units(text):
    return _UNIT.findall(_units_text(text))


def _measure(unit):
    top, _, bottom = unit.partition("/")
    dims = [_SCALE[top][0]]
    scale = _SCALE[top][1]
    if bottom:
        dims.append(_SCALE[bottom][0])
        scale /= _SCALE[bottom][1]
    return tuple(dims), scale


def _one(values, question):
    values = set(values)
    if len(values) > 1:
        raise Clarify(question)
    return next(iter(values), None)


def _field_role(field, protocol, name):
    # Only local clauses naming this input may supply metadata for its column.
    clauses = re.findall(r"\b" + name + r"\s+(?:is|stores?|contains?|represents?|measures?|in)\s+([^.;,]{1,65})", protocol)
    desc = field + " " + " ".join(re.split(r"\b(?:and|then|with|while|by|to|report)\b", c)[0] for c in clauses)
    unit = _one(_units(desc), "Which units belong to the " + name + " column?")
    if unit:
        dim, _ = _measure(unit)
        role = dim[0] if len(dim) == 1 else "ratio"
    else:
        role = _one(re.findall(r"\b(mass|volume)\b", desc), "Which quantity does the " + name + " column contain?")
    if role in ("mass", "volume", "amount"):
        local = _units_text(protocol)
        labels = re.findall(r"\b" + role + r"\s*(?:is\s+)?(?:recorded\s+|measured\s+|given\s+)?(?:in\s+)?[\[(]?\s*("
                            + _SYMBOL + r"(?:/" + _SYMBOL + r")?)\b", local)
        unit = _one(([unit] if unit else []) + labels, "Which input unit is specified for the " + role + "?")
    return role, unit


_S = r"(?:signals?|responses?|readings?|intensity|absorbance|counts?|sensor output)"
_K = r"(?:known(?: values?)?|concentrations?|amount|reference values?|reference level|mass)"
_NAMES = {"signal", "factor", "row", "sample", "standard", "value", "the", "a", "an", "in", "of", "per"}


def _axes(protocol, signal_field):
    # Collapse noun phrases before extracting directional relations.
    words = re.findall(r"[a-z]+", signal_field)
    aliases = [re.escape(w) for w in words if len(w) > 2 and w not in _NAMES
               and not re.fullmatch(_K, w) and w not in _SCALE]
    sig = _S if not aliases else "(?:" + "|".join([_S, *aliases]) + ")"
    text = re.sub(r"\b" + sig + r"\b", " @s ", protocol)
    text = re.sub(r"\b" + _K + r"\b", " @k ", text)
    text = re.sub(r"\b(?:the|a|an|sample|measured|instrument|observed|sensor|standard[s]?|nominal|true|calibrant|certified|column|batch|values?|levels?|linear|linearly|its|their)\b", " ", text)
    text = re.sub(r"\([^()]*\)", " ", text) if not re.search(r"\([xy]\)", text) else text
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(@[sk])(?:\s+\1)+", r"\1", text)
    directions = set()
    for y, x, fit in (("@s", "@k", "inverse"), ("@k", "@s", "direct")):
        relation = r"\s+(?:on|upon|vs\.?|versus|against|(?:as|is) (?:a )?function of|as (?:a )?response to|as dependent (?:variable )?on|as (?:a )?function in)\s+"
        equation = y + r"\s*=\s*[^.,;=]{0,32}" + x
        if (re.search(y + relation + x, text) or re.search(equation, text)
                or re.search(r"(?:fit(?:ting)?|regress|model)\s+" + y + r"\s+(?:from|using|by)\s+" + x, text)):
            directions.add(fit)
        for axis, role in (("y", y), ("x", x)):
            label = axis + r"(?:[ -]axis)?"
            designation = "dependent" if axis == "y" else "independent"
            if (re.search(role + r"\s*(?:\(\s*" + label + r"\s*\)|\bas\s+" + label + r"\b|(?:is|as) (?:the )?" + designation + r" variable)", text)
                    or re.search(r"\b" + axis + r"\s*=\s*" + role, text)):
                directions.add(fit)
    if re.search(r"\b(?:invert|inverting|inversion|inverted|solve (?:it |the (?:line|fit|equation) )?for (?:the )?(?:known|concentration))\b", protocol):
        directions.add("inverse")
    return _one(directions, "Which standard column is the dependent variable, and should the fitted line be inverted?")


def _blank(protocol):
    """Extract evidence for the blank value without selecting an operation order."""
    sources = set()
    protocol = re.sub(r"(?:subtract(?:ing)?|minus) (?:the )?(?:fitted |calibration )?intercept\b", "", protocol)
    if not re.search(r"\b(?:blank|baseline|offset|tare|subtract|minus|deduct)\b", protocol):
        return sources
    number = r"([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?)"
    constants = (r"(?:blank|baseline|offset|tare)(?:\s+(?:signal|reading|value|offset))?\s*(?:of|is|=|equals|:|at)?\s*" + number,
                 r"(?:subtract|minus|deduct)\s+" + number,
                 number + r"\s*(?:as the |as a )?(?:blank|baseline|offset|tare)\b")
    for pat in constants:
        for match in re.finditer(pat, protocol):
            literal = match[1]
            if len(literal) > 32 or ("e" in literal and abs(int(literal.split("e")[1])) > 24):
                raise Clarify("What finite blank value should be subtracted?")
            n = Fraction(literal)
            if abs(n) > 10**24 or (n and abs(n) < Fraction(1, 10**24)):
                raise Clarify("What finite blank value should be subtracted?")
            sources.add(str(float(n)))
    col = 1 if re.search(r"(?:first|last) standard(?:'s)? (?:known|assigned) value", protocol) else 0
    for index, pat in (("0", r"(?:first|initial|first-listed) (?:calibration )?(?:standard|row|pair|reference)|standards?\[0\]"),
                       ("len(standards) - 1", r"last (?:calibration )?(?:standard|row|pair|reference)")):
        if re.search(pat, protocol):
            sources.add(f"standards[{index}][{col}]")
    for name, pat in (("mean", "mean|average"), ("min", "minimum|lowest|min"), ("max", "maximum|highest|max")):
        if re.search(r"\b(?:" + pat + r")\s+(?:of\s+)?(?:all\s+)?(?:the\s+)?(?:batch\s+)?(?:standard|reference)(?:s|'s)?[ -]+(?:signals?|readings?|responses?)", protocol):
            sources.add(f"{name}(column(standards, 0))")
    if not sources:
        raise Clarify("What blank value or identifiable standard reading should be subtracted?")
    if not re.search(r"subtract|minus|deduct|correct|remove|less\b|net\b|difference|zero[- ]adjust|\b-\s*(?:the )?blank", protocol):
        raise Clarify("How should the blank be combined with the sample reading?")
    if len(sources) != 1 or re.search(r"subtract\w* (?:the )?(?:raw |sample )?(?:signal|reading) from", protocol):
        raise Clarify("Which single blank should be subtracted from the sample?")
    return sources


def _factor_ops(p, field, roles, fit, has_blank):
    sr, fr = roles
    mass_volume = (sr, fr) in (("mass", "volume"), ("amount", "volume"), ("volume", "mass"), ("volume", "amount"))
    terms = ["factor", "dilution", "multiplier", "divisor"]
    if fr:
        terms.append(fr)
    if field and len(field) <= 70:
        terms.append(field)
    obj = r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b"
    reverse = r"\bdivid\w*\s+(?:the )?(?:row )?" + obj + r"\s+by\s+(?:the )?(?:raw |sample |corrected )?(?:signal|reading|volume)\b"
    # Actions may have an intervening operand, e.g. "divide the fitted concentration by the factor".
    ops = {"rdiv"} if re.search(reverse, p) else set()
    operations_text = re.sub(reverse, "", p)
    unused = re.search(r"\b(?:ignore|omit|discard)\s+(?:the |any )?(?:row )?" + obj
                       + r"|\bfactor\s+(?:is\s+)?(?:unused|ignored)|\bwithout (?:any )?(?:dilution|factor)\b", p)
    for op, verb, symbol in (("mul", r"multipl(?:y|ied|ying|ication)|times|scal(?:e[ds]?|ing)", r"\*"),
                             ("div", r"divid(?:e|ed|ing)|normaliz(?:e|ed|ing)|per", r"/")):
        action = r"\b(?:" + verb + r")\b((?:(?!\b(?:and|then|before|after|multipl\w*|divid\w*|subtract\w*)\b)[^.;,]){0,72})"
        if any(re.search(obj, m[1]) for m in re.finditer(action, operations_text)) or re.search(symbol + r"\s*(?:row\s+)?" + obj, p):
            ops.add(op)
    if re.search(obj + r"\s*\*|\bproduct of\b[^.;]{0,65}" + obj, p):
        ops.add("mul")
    if mass_volume and re.search(r"\b(?:divid\w*|concentration|densit\w*|ratio|per)\b|/", p):
        natural = "div" if fr == "volume" else "rdiv"
        if natural == "rdiv" and "div" in ops and re.search(r"\b(?:mass|factor)\b[^.;,]{0,35}\bby\b[^.;,]{0,20}\b(?:volume|signal)\b", p):
            ops.remove("div")
        ops.add(natural)
    elif re.search(r"\bfactor\s*/\s*(?:signal|reading)", p):
        ops.add("rdiv")
    if unused or field in ("unused", "none", "ignored") or "omit row adjustment" in p:
        return ops | {"none"}
    if ops:
        return ops
    if (re.search(r"\bdilution\b", p) or ("dilution" in field and "factor" in p)) and not re.search(r"\b(?:fraction|ratio)\b", p):
        return {"mul"}
    if re.search(r"\b(?:factor|multiplier|divisor)\b", p):
        raise Clarify("Should the row factor multiply or divide the result, and at which step?")
    if re.search(r"dilution|multiplier|divisor|volume", field):
        raise Clarify("How should the factor column be used in this protocol?")
    if fit or has_blank or re.search(r"(?:report|return|use) (?:the )?(?:raw |unadjusted )?(?:signal|reading|mass)", p):
        return {"none"}
    raise Clarify("What numerical operation should convert the signal and factor into the requested result?")


def _order(protocol, actions, is_dilution):
    """Build precedence constraints. An unordered noncommuting pair remains ambiguous."""
    events = {
        "fit": r"\b(?:fit(?:ted|ting)?|regress(?:ion)?|calibrat(?:e|ing|ion)|invert(?:ing)?|interpolat(?:e|ion))\b",
        "blank": r"\b(?:subtract(?:ed|ing|ion)?|deduct(?:ing)?|minus|blank[- ]correct(?:ed|ing|ion)?)\b",
        "factor": r"\b(?:multipl(?:y|ied|ying|ication)|divid(?:e|ed|ing)|scal(?:e|ed|ing)|times|appl(?:y|ying)|normaliz(?:e|ing))\b",
    }
    edges = set()

    def connect(left, right, reverse=False):
        # The nearest named actions delimit a sequencing word.
        before = [(m.end(), a) for a in actions for m in re.finditer(events[a], left)]
        after = [(m.start(), a) for a in actions for m in re.finditer(events[a], right)]
        if before and after:
            a, b = max(before)[1], min(after)[1]
            if a != b:
                edges.add((b, a) if reverse else (a, b))

    for m in re.finditer(r"\b(?:before|after|then|followed by|next|subsequently)\b", protocol):
        left = protocol[:m.start()].strip(" ,;.")
        right = protocol[m.end():]
        if m[0] in ("after", "before") and (not left or protocol[:m.start()].rstrip().endswith(".")):
            clauses = re.split(r"[,;]", right, maxsplit=1)
            if len(clauses) == 2:
                connect(*clauses, reverse=m[0] == "before")
        else:
            connect(left, right, reverse=m[0] == "after")
    if {"factor", "blank"} <= actions:
        if re.search(r"(?:multipl\w*|divid\w*|scale)\s+(?:the )?(?:resulting |blank[- ]corrected|net)\b", protocol):
            edges.add(("blank", "factor"))
        if not any({a,b} == {"blank","factor"} for a,b in edges):
            if re.search(events["blank"] + r".{0,120}?(?:\band\b|[.;,])\s*(?:finally\s+)?" + events["factor"], protocol):
                edges.add(("blank", "factor"))
            elif re.search(events["factor"] + r".{0,120}?(?:\band\b|[.;,])\s*" + events["blank"], protocol):
                edges.add(("factor", "blank"))
    if {"fit", "factor"} <= actions and not any({a,b} == {"fit","factor"} for a,b in edges):
        if re.search(r"(?:multipl\w*|divid\w*|scal\w*) (?:the )?(?:raw|sample|measured) signal", protocol):
            edges.add(("factor", "fit"))
        elif is_dilution or re.search(r"(?:multipl\w*|divid\w*|scal\w*) (?:the )?(?:back[- ]calculated|calibrated|result|estimate|concentration|predicted|fitted|calculated|interpolated)", protocol):
            edges.add(("fit", "factor"))
    return edges


def _conversion(p, output, signal_unit, factor_unit, fit, op):
    target = _one(_units(output), "Which single output unit is required?")
    mentioned = _units(p)
    destination = r"(" + _SYMBOL + r"(?:/" + _SYMBOL + r")?)\b"
    unit_text = _units_text(p)
    reported = re.findall(r"\b(?:report|express|return)\w*\s+(?:(?:the |final |result |it |value |concentration |in |as )+)?" + destination, unit_text)
    reported += re.findall(r"\bconvert\w*\b[^.;]{0,50}?\bto\s+" + destination, unit_text)
    if target and any(u != target for u in reported):
        raise Clarify("Which output unit should be used where the protocol and unit field differ?")
    # Prefer units attached to standard known values, never a unit in a report clause.
    if fit:
        standards = re.findall(r"\b(?:known(?:\s+(?:standard|values?|concentrations?|mass))?|standard concentrations?)\s*(?:are\s+|given\s+|expressed\s+)?(?:in\s+)?[\[(]?\s*(" + _SYMBOL + r"(?:/" + _SYMBOL + r")?)\b", _units_text(p))
        source = _one(standards, "In which units are the known standard values expressed?")
    else:
        source = signal_unit
        if factor_unit and op in ("div", "rdiv") and signal_unit:
            a, b = (signal_unit, factor_unit) if op == "div" else (factor_unit, signal_unit)
            if "/" in a or "/" in b:
                raise Clarify("Which output unit should result from dividing these quantities?")
            source = a + "/" + b
        elif factor_unit and op == "mul":
            raise Clarify("Which units result from multiplying these two measurements?")
    if not target:
        if source and output not in ("", "au", "a.u.", "units", "arbitrary units"):
            raise Clarify("How should the input measurement be converted to the supplied output unit?")
        return Fraction(1)
    if not source:
        if any(unit != target for unit in mentioned) or re.search(r"\bconvert\b", p) or factor_unit:
            raise Clarify("Which input units and conversion should be used to obtain the requested unit?")
        return Fraction(1)
    sd, ss = _measure(source)
    td, ts = _measure(target)
    if sd != td:
        raise Clarify("How do the stated input quantities produce the requested output dimension?")
    return ss / ts


def _supported_protocol(p):
    # Drop explicit exemptions before matching operations. A different negation
    # or a conditional changes the numerical specification and needs clarification.
    p = re.sub(r"\b(?:do not|never|not|without) (?:forc\w*|constrain\w*) (?:it |the (?:fit|line) )?(?:to (?:go |pass )?)?through (?:the )?origin", "", p)
    p = re.sub(r"\b(?:no|without) (?:a |any )?dilution(?: correction| adjustment)?\b", "omit row adjustment", p)
    unsupported = (
        r"\b(?:or|unspecified|possibly|maybe|tbd|optional\w*|nonlinear|quadratic|polynomial|weight\w*|variance|"
        r"uncertaint\w*|median|log(?:arithm\w*|10)?|sqrt|square root|exponential|logistic|robust|piecewise|"
        r"interpolate between|interpolation|z[ -]score|outlier\w*|residual\w*|normal distribution|"
        r"significant (?:figures|digits)|clamp|absolute value|add|plus|square|double|halve|twice|raised to|"
        r"if|unless|whenever|conditionally|only (?:for|when)|replace|clip\w*|external|recorded elsewhere|"
        r"additional|coefficients?|do not|must not|never|except|threshold|metadata|exclude\w*|discard the first)\b"
    )
    if re.search(unsupported, p) or "unknown direction" in p:
        raise Clarify("Which unconditional calculation should be applied using only the two columns and supplied standards?")
    if re.search(r"through (?:the )?origin|(?:no|without|zero|fixed) (?:an? )?intercept|intercept[^.;]{0,35}\b(?:fixed|set|equal\w*|zero)\b|intercept\s*=", p):
        raise Clarify("Can the intercept be freely estimated from both standard columns?")
    return p


def _render(model, blank, op, order, scale, precision):
    lines = ["def analyze(standards, signal, factor):", "    value = signal"]
    for step in order:
        if step == "fit":
            lines.extend(["    readings = column(standards, 0)", "    known = column(standards, 1)"])
            if model == "inverse":
                lines.append("    value = (value - intercept(known, readings)) / slope(known, readings)")
            else:
                lines.append("    value = slope(readings, known) * value + intercept(readings, known)")
        elif step == "blank":
            lines.append("    value = value - " + blank)
        else:
            expr = {"mul": "value * factor", "div": "value / factor", "rdiv": "factor / value"}[op]
            lines.append("    value = " + expr)
    if scale != 1:
        lines.append(f"    value = value * {scale.numerator} / {scale.denominator}")
    lines.append("    return " + ("value" if precision is None else f"round(value, {precision})"))
    return "\n".join(lines) + "\n"


def _synthesize(request):
    if not isinstance(request, dict) or not isinstance(request.get("fields"), dict):
        raise Clarify("Please identify the signal and factor columns and supply a numerical protocol.")
    fields = request["fields"]
    p, sf, ff, unit = map(_text, (request.get("protocol"), fields.get("signal"), fields.get("factor"), request.get("unit")))
    if not all((p, sf, ff, unit)) or len(p) > 12000:
        raise Clarify("Please supply a concise protocol, signal and factor field names, and the output unit.")
    p = _supported_protocol(p)
    fit = bool(re.search(r"\b(?:fit(?:ted|ting)?|regress\w*|ols|calibrate|calibration(?! standards?\b)|least[ -]squares|standard curve)\b", p))
    blanks = _blank(p)
    if fit and blanks and re.search(r"(?:all|both|each|every) (?:standard|reading|signal)|standards and (?:the )?samples", p):
        raise Clarify("How are the standard readings and the sample corrected before fitting?")
    direction = _axes(p, sf) if fit else "identity"
    sr, su = _field_role(sf, p, "signal")
    fr, fu = _field_role(ff, p, "factor")
    if fr in ("volume", "mass", "amount") and sr in ("volume", "mass", "amount") and not (su and fu):
        raise Clarify("What are the units of both the mass or amount and the volume measurements?")
    ops = _factor_ops(p, ff, (sr, fr), fit, bool(blanks))
    if not fit and not blanks and ops == {"none"} and not re.search(
        r"(?:report|return|use) (?:the )?(?:raw |unadjusted |sample )?(?:signal|reading|mass)\b", p
    ):
        raise Clarify("Which numerical result should be derived from the input signal?")

    # Enumerate the grammar independently of the constraints. Only a unique
    # feasible source is accepted; equally supported directions/orders abstain.
    precision_match = re.search(r"\bround\w*\b[^.;]{0,40}?\b(\d{1,2}) decimal places?\b", p)
    whole = bool(re.search(r"\bround\w*\b[^.;]{0,45}\b(?:nearest (?:whole number|integer)|zero decimal places)\b", p))
    if "round" in p and not whole and (not precision_match or int(precision_match[1]) > 12):
        raise Clarify("How many decimal places should the final result be rounded to?")
    precision = 0 if whole else int(precision_match[1]) if precision_match else None
    if precision is not None and re.search(r"\bround\w*\b[^.;]{0,100}\b(?:before|then|afterwards)\b", p):
        raise Clarify("Should rounding occur only after all corrections and unit conversions?")
    numeric_ops = re.findall(r"\b(multipl\w*|divid\w*)\s+(?:(?:the )?(?:result|value|it)\s+)?by\s+([+-]?(?:\d+(?:\.\d+)?|\.\d+))\b", p)
    if re.search(r"\b(?:multipl\w*|divid\w*)\s+by\s+(?:two|three|four|five|ten|one hundred|a thousand)\b", p) or len(numeric_ops) > 1:
        raise Clarify("Please specify how the additional scaling relates to the output unit.")
    matches = set()
    for model, op, blank in product(("identity", "direct", "inverse"), ("none", "mul", "div", "rdiv"), blanks or (None,)):
        if (model != "identity") != fit or (direction and model != direction) or op not in ops:
            continue
        active = {s for s, use in (("fit", fit), ("blank", blank is not None), ("factor", op != "none")) if use}
        constraints = _order(p, active, "dilut" in p or "dilut" in ff)
        scale = _conversion(p, unit, su, fu, fit, op)
        if numeric_ops:
            verb, literal = numeric_ops[0]
            if len(literal) > 24:
                raise Clarify("Which unit conversion is required?")
            stated = Fraction(literal)
            if scale == 1 or stated <= 0 or (stated if verb.startswith("multipl") else 1/stated) != scale:
                raise Clarify("How does the specified numeric adjustment relate to the input and output units?")
        for seq in permutations(sorted(active)):
            if all(seq.index(a) < seq.index(b) for a,b in constraints):
                matches.add(_render(model, blank, op, seq, scale, precision))
    if len(matches) != 1:
        if fit and not direction:
            raise Clarify("Should the line fit signal on known value and be inverted, or fit known value on signal directly?")
        raise Clarify("Please specify the blank source, factor operation, and the order of the applicable calculation steps.")
    return {"source": matches.pop()}


def solve(request):
    try:
        return _synthesize(request)
    except Clarify as exc:
        return {"needs_input": str(exc)}
