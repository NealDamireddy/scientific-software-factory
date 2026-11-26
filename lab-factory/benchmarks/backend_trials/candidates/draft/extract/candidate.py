"""Extract a cited draft from controlled English for two simulated displays."""

import math
import operator
import re


NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
UNIT = {
    "set_temperature": r"(?:°\s*c(?:elsius)?|degrees?\s+c(?:elsius)?|celsius|c)\b",
    "set_wavelength": r"(?:nm|nanomet(?:er|re)s?)\b",
}
SYMBOL = {"set_temperature": "C", "set_wavelength": "nm"}
SUBJECT = {
    "set_temperature": r"\b(?:temperature|thermal setpoint|set_temperature)\b",
    "set_wavelength": r"\b(?:wavelength|set_wavelength)\b",
}
ZERO = r"\b(?:zero(?:ed|ing)?|re-zero(?:ed|ing)?)\b"
READ = r"\b(?:read(?:s|ings?)?|read_display|readout|display reads?)\b"
DISPLAY = r"\b(?:display(?:ed)?|readout|readings?|screen|indication)\b"
ACTION = (
    r"zero|re-zero|set(?:_temperature|_wavelength)?|select|choose|adjust|tune|dial|"
    r"read(?:_display)?|record|note|take|capture|measure|check|wait|press|"
    r"open|close|start|stop|switch|turn|save|log|enable|disable|calibrate"
)
NEGATIVE = (
    r"\b(?:not|never|cannot|can't|unsupported|unavailable|disabled|forbidden|"
    r"prohibited|mustn't|don't|do not|no support|doesn't|incapable|lacks?)\b"
)
NONDETERMINISTIC = (
    r"\b(?:if|unless|optionally|optional|may|might|can|could|either|or|before|after|"
    r"until|repeat|twice|thrice|approximately|about|typically|example|normally|instead)\b"
)
STOP = set(
    "a an the your on of for to in is as at with and using use run perform carry out "
    "please do draft prepare create how i me need would like procedure procedures "
    "protocol instructions steps operational operation sop standard operating my "
    "our this that model device simulated simulator simulation how should would you "
    "give walk through execute complete safely from applicable documented according "
    "instruction step guide tell me write generate perform following".split()
)
GENERIC_GOAL = set("check test verification validate verify reference display "
                   "instrument perform conduct please routine measurement setting".split())


def _normalize(text):
    return text.lower().translate(str.maketrans({"−": "-", "–": "-", "—": "-", "’": "'"}))


def _revision(revision):
    match = re.fullmatch(
        r"\s*(?:(?:rev(?:ision)?|r|v)\s*[-.]?\s*)?(\d+(?:[.\-/]\d+)*)\s*",
        str(revision).lower(),
    )
    if not match:
        raise ValueError("unrecognized revision")
    return tuple(int(part) for part in re.findall(r"\d+", match[1]))


def _editions(request):
    cutoff = _revision(request["as_of"])
    model = request["model"]
    if not isinstance(model, str) or not model.strip() or model == "*":
        raise ValueError("missing model")
    editions = {}
    for doc in request["documents"]:
        if doc["model"] not in (model, "*") or doc["kind"] not in ("sop", "manual"):
            continue
        revision = _revision(doc["revision"])
        if revision > cutoff:
            continue
        family, delimiter, suffix = doc["id"].rpartition("@")
        if not family or not delimiter or not suffix:
            raise ValueError("missing source identifier")
        if _revision(suffix) != revision:
            raise ValueError("source identifier and revision disagree")
        key = (doc["kind"], family)
        rank = (doc["model"] == model, revision)
        current = editions.get(key)
        if current is None or rank > current[0]:
            editions[key] = (rank, [doc])
        elif rank == current[0] and doc not in current[1]:
            current[1].append(doc)
    if any(len(group) != 1 for _, group in editions.values()):
        raise ValueError("conflicting editions")
    return [group[0] for _, group in editions.values()]


def _words(text):
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words} - STOP


def _choose_sop(request, docs):
    words = _words(request["goal"]) - _words(request["model"])
    choices = []
    for doc in docs:
        if doc["kind"] != "sop":
            continue
        family = doc["id"].rsplit("@", 1)[0]
        source = _words(family + " " + doc["text"])
        if "thermometer" in source or "temperature" in source:
            source.update(("temperature", "thermometer"))
        if "wavelength" in source or "nm" in source:
            source.add("optical")
        overlap = words & source
        if overlap and (words - GENERIC_GOAL) <= source:
            choices.append(((len(overlap), doc["model"] != "*"), doc))
    if not choices:
        raise ValueError("no applicable SOP")
    best = max(score for score, _ in choices)
    matches = [doc for score, doc in choices if score == best]
    if len(matches) != 1:
        raise ValueError("ambiguous goal")
    return matches[0]


def _sentences(text):
    # Preserve decimal points, including leading decimals and dotted revisions.
    return re.split(r"(?:[;\n]+|(?<!\.)[.!?](?![.\d])\s*)", _normalize(text))


def _heading(clause, goal):
    if re.search(rf"{NEGATIVE}|{NONDETERMINISTIC}", clause):
        return False
    # Explicit title or purpose lines may repeat the requested goal verbatim.
    title_words = {"title", "purpose", "goal", "reference", "check", "test", "verification",
                   "optical", "display", "thermometer", "describe", "describes", "cover", "covers"}
    return _words(clause) <= (_words(goal) | title_words)


def _directive(clause):
    # Finite verbs following an explicit operator, and unambiguous passive
    # constructions, describe the same local action as an imperative.
    clause = re.sub(r"^(?:the operator|the user|you)\s+(?:(?:must|should)\s+)?", "", clause)
    gerunds = {"zeroing": "zero", "setting": "set", "selecting": "select",
               "choosing": "choose", "reading": "read", "recording": "record"}
    clause = re.sub(r"^(?:begin|start|finish|end) by (\w+)\b",
                    lambda m: gerunds.get(m[1], m[0]), clause)
    for pattern, replacement in (
        (r"^(?:zeros|zeroes)\b", "zero"), (r"^sets\b", "set"),
        (r"^selects\b", "select"), (r"^chooses\b", "choose"),
        (r"^reads\b", "read"), (r"^records\b", "record"),
        (r"^(?:the )?([\w -]+?) (?:is|must be|should be) zeroed\b", r"zero \1"),
        (r"^(?:the )?(wavelength|temperature) (?:is|must be|should be) set\b", r"set \1"),
        (r"^(?:the )?(display|readout) (?:is|must be|should be) read\b", r"read \1"),
    ):
        clause = re.sub(pattern, replacement, clause)
    return clause


def _actions(text, goal):
    actions = []
    text = re.sub(r"(?m)^\s*(?:step\s+)?\d+[.)]\s+", "", text, flags=re.I)
    for sentence in _sentences(text):
        clauses = re.split(
            rf"\s*,\s*|\b(?:and\s+then|then|followed by)\b|"
            rf"\band\s+(?=(?:{ACTION})(?:s|es)?\b)", sentence
        )
        for clause in clauses:
            clause = clause.strip(" \t-•")
            if not clause:
                continue
            # A heading can introduce the first operation on the same line.
            if ":" in clause:
                title, clause = clause.split(":", 1)
                if not (_heading(title, goal) or re.fullmatch(r"(?:step )?\d+", title)):
                    raise ValueError("instruction in heading")
                clause = clause.strip()
            clause = re.sub(
                r"^(?:(?:step\s+)?\d+[)\].:-]?\s+|(?:first|next|finally|last)\s+)+", "", clause
            )
            if not clause or clause in {"first", "next", "last", "finally"}:
                continue
            if re.search(rf"{NEGATIVE}|{NONDETERMINISTIC}", clause):
                raise ValueError("conditional or ambiguous direction")
            clause = _directive(clause)
            if re.match(r"(?:zero|re-zero)\b", clause):
                operation = "zero"
            elif re.match(r"(?:read(?:_display)?|record|note|capture|take)\b", clause):
                if not (re.search(DISPLAY, clause) or clause in ("read", "read_display")):
                    raise ValueError("unrecognized read target")
                operation = "read_display"
            elif re.match(r"(?:set(?:_wavelength|_temperature)?|select|choose|adjust|tune|dial)\b", clause):
                dimensions = [
                    command for command in UNIT
                    if re.search(SUBJECT[command], clause)
                    or re.search(rf"{NUMBER}\s*{UNIT[command]}", clause)
                ]
                if len(dimensions) != 1:
                    raise ValueError("ambiguous setting")
                operation = dimensions[0]
            elif not actions and _heading(clause, goal):
                continue
            else:
                raise ValueError("unparsed clause")
            if re.search(r"\b(?:and|while|plus|without|is|are|was|were)\b", clause):
                raise ValueError("operation is not a single directive")
            value = unit = None
            if operation in UNIT:
                if re.search(r"[<>≤≥~]|\b(?:above|below|under|over|less|more|greater|least|most|minimum|maximum|between|within|by)\b", clause):
                    raise ValueError("no exact setpoint")
                values = re.findall(rf"({NUMBER})\s*{UNIT[operation]}", clause)
                if len(values) != 1 or len(re.findall(NUMBER, clause)) != 1:
                    raise ValueError("missing or ambiguous setting")
                value = float(values[0])
                if not math.isfinite(value):
                    raise ValueError("nonfinite setting")
                unit = SYMBOL[operation]
            elif re.search(r"\d", clause):
                raise ValueError("unexpected numeric argument")
            actions.append((operation, value, unit))
    if not actions:
        raise ValueError("empty SOP")
    return actions


def _relevant(sentence, operation):
    if operation == "zero":
        return re.search(ZERO, sentence)
    if operation == "read_display":
        return (re.search(READ, sentence)
                or re.search(r"\b(?:record|capture|note)\b.*" + DISPLAY, sentence))
    return (re.search(SUBJECT[operation], sentence)
            or re.search(rf"{NUMBER}\s*{UNIT[operation]}", sentence))


CAPABILITY = (
    r"\b(?:support(?:s|ed)?|allow(?:s|ed)?|enable(?:s|d)?|available|accept(?:s|ed)?|"
    r"permit(?:s|ted)?|can|may|able to|capable|capabilit(?:y|ies)|commands?|"
    r"operations?|functions?|controls?|buttons?|features?)\b"
)
COMPARISONS = {
    "at least": operator.ge, "minimum": operator.ge, "min": operator.ge,
    "no less than": operator.ge, ">=": operator.ge, "≥": operator.ge,
    "at most": operator.le, "maximum": operator.le, "max": operator.le,
    "up to": operator.le, "no more than": operator.le, "<=": operator.le, "≤": operator.le,
    "above": operator.gt, "greater than": operator.gt, ">": operator.gt,
    "below": operator.lt, "less than": operator.lt, "<": operator.lt,
}
COMPARATOR = "|".join(map(re.escape, COMPARISONS))


def _manual_evidence(doc, operation, value):
    """Return None for silence, False for insufficient/contrary evidence, True for support."""
    sentences = [s for s in _sentences(doc["text"]) if _relevant(s, operation)]
    if not sentences:
        return None
    forbidden = r"\b(?:no\s+(?:display\s+)?(?:read|zero)|except|exclud\w*|disallow\w*|if|unless|only when)\b"
    if any(re.search(rf"{NEGATIVE}|{forbidden}", s) for s in sentences):
        return False
    if operation not in UNIT:
        if operation == "read_display":
            sentences = [s for s in sentences if re.search(DISPLAY, s) or "read_display" in s]
        return any(re.search(CAPABILITY, s) or
                   re.match(r"\s*(?:zero|read|read_display|record)\b", s) for s in sentences)

    unit = UNIT[operation]
    endpoint = rf"({NUMBER})\s*(?:{unit})?"
    range_pattern = rf"{endpoint}\s*(?:-|to\b|through\b|\.\.|\band\b)\s*{endpoint}"
    comparison = (rf"(?<!\w)({COMPARATOR})(?:\s+(?:allowed|supported|operating|wavelength|"
                  rf"temperature|setting|value|of|is))*\s*[:=]?\s*({NUMBER})\s*{unit}")
    bounds = []
    allowed = set()
    for s in sentences:
        # Keep a second dimension's specifications out of this comparison.
        other = "set_temperature" if operation == "set_wavelength" else "set_wavelength"
        if _relevant(s, other) and re.search(rf"{NUMBER}\s*{UNIT[other]}", s):
            return False
        if re.search(r"\b(?:increments?|multiples?|exclusive|excluding|measured|observed)\b", s):
            return False
        if not re.search(rf"{NUMBER}\s*{unit}", s):
            continue
        pairs = list(re.finditer(range_pattern, s))
        found_range = False
        for pair in pairs:
            if not re.search(rf"{NUMBER}\s*{unit}", pair[0]):
                continue
            if " and " in pair[0] and "between" not in s[:pair.start()]:
                continue
            lower, upper = map(float, pair.groups())
            bounds.append(lower <= value <= upper)
            found_range = True
        comparisons = re.findall(comparison, s)
        for op, number in comparisons:
            bounds.append(COMPARISONS[op](value, float(number)))
        if not found_range and not comparisons:
            numbers = {float(n) for n in re.findall(rf"({NUMBER})\s*{unit}", s)}
            if re.search(r"\b(?:only|fixed)\b", s):
                bounds.append(value in numbers)
            elif re.search(rf"{CAPABILITY}|\b(?:set|select)\b", s):
                allowed.update(numbers)
            elif re.search(r"\b(?:limit|minimum|maximum|bound|range)s?\b", s):
                return False
    return all(bounds) and (bool(bounds) or value in allowed)


def _citation(manuals, operation, value):
    evidence = []
    for doc in manuals:
        verdict = _manual_evidence(doc, operation, value)
        if verdict is not None:
            evidence.append((doc["model"] != "*", doc["id"], verdict))
    if not evidence:
        raise ValueError("no manual evidence")
    best = max(specific for specific, _, _ in evidence)
    applicable = [(source, supported) for specific, source, supported in evidence if specific == best]
    if not all(supported for _, supported in applicable):
        raise ValueError("manual evidence insufficient or contradictory")
    return min(source for source, _ in applicable)


def solve(request):
    try:
        docs = _editions(request)
        sop = _choose_sop(request, docs)
        manuals = [doc for doc in docs if doc["kind"] == "manual"]
        steps = [
            {"command": op, "value": value, "unit": unit,
             "citations": [sop["id"], _citation(manuals, op, value)]}
            for op, value, unit in _actions(sop["text"], request["goal"])
        ]
        return {"status": "draft", "steps": steps}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return {"status": "needs_input", "steps": []}
