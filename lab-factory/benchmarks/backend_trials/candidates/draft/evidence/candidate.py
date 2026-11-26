"""Offline, evidence-first drafting for simulated optical and temperature displays."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field


def _normalize(text):
    return text.casefold().replace("−", "-").replace("℃", "°c").replace("_", " ")


def _edition(value):
    # A cutoff and its revisions must use the same numbering convention.
    match = re.fullmatch(r"(?:rev(?:ision)?[ ._-]*|[rv])?(\d+(?:[.-]\d+)*)", str(value).strip(), re.I)
    if match:
        return tuple(int(part) for part in re.split(r"[.-]", match[1]))
    return None


@dataclass(frozen=True)
class Source:
    id: str
    family: str
    edition: tuple
    model: str
    kind: str
    text: str


def _sources(request):
    model = request["model"]
    cutoff = _edition(request["as_of"])
    docs = request["documents"]
    if not isinstance(model, str) or not model.strip() or not cutoff or not isinstance(docs, list):
        raise ValueError
    groups = defaultdict(list)
    for doc in docs:
        if doc["model"] not in (model, "*") or doc["kind"] not in ("sop", "manual"):
            continue
        edition = _edition(doc["revision"])
        if edition is None:
            raise ValueError
        if edition > cutoff:
            continue
        source_id = doc["id"]
        family, sep, suffix = source_id.rpartition("@")
        if not family or not sep or not suffix or not isinstance(doc["text"], str):
            raise ValueError
        if _edition(suffix) not in (None, edition):
            raise ValueError
        source = Source(source_id, family, edition, doc["model"], doc["kind"], doc["text"])
        groups[source.kind, source.family, source.model].append(source)
    latest = []
    for editions in groups.values():
        top = max(source.edition for source in editions)
        winners = {source for source in editions if source.edition == top}
        if len(winners) != 1:
            raise ValueError
        latest.extend(winners)
    specific = {(s.kind, s.family) for s in latest if s.model != "*"}
    return [s for s in latest if s.model != "*" or (s.kind, s.family) not in specific]


_STOP = set("""
    a an the in on to of for with at and from as using by my this that our please
    goal i we want need would like how do me create make generate prepare provide
    run perform carry out follow draft procedure protocol sop steps step sequence
    ordered grounded cited simulated simulation device instrument model check checking
    verify verification test testing conduct routine workflow instructions latest eligible current applicable
""".split())
_ALIASES = {"optics": "optical", "thermometry": "thermometer", "thermometric": "thermometer",
            "displays": "display", "readout": "display", "references": "reference",
            "referencing": "reference", "readings": "read", "reading": "read"}


def _words(text):
    return {_ALIASES.get(w, w) for w in re.findall(r"[a-z]+|\d+", _normalize(text))}


def _resolve(goal, model, sops):
    if not isinstance(goal, str):
        return None
    wanted = _words(goal) - _STOP - _words(model)
    if not wanted:
        return None
    matches = []
    for source in sops:
        words = _words(source.family + " " + source.text)
        if words & {"wavelength", "nanometers", "nm"}:
            words.add("optical")
        if "temperature" in words:
            words.add("thermometer")
        if wanted <= words:
            matches.append(source)
    specific = [s for s in matches if s.model == model]
    matches = specific or matches
    return matches[0] if len(matches) == 1 else None


_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_UNIT = r"(?:nm|nanomet(?:er|re)s?|(?:°\s*|degrees?\s*)?(?:celsius|c))\b"
_AMOUNT = re.compile(rf"(?<![a-z\d.])({_NUMBER})\s*({_UNIT})")
_SET = r"(?:set(?:ting)?|select(?:ing)?|adjust(?:ing)?|tun(?:e|ing)|program(?:ming)?|dial(?:ing)?)"
_PARAM = r"(?:(?:the|a|an|target|optical|reference|display|nominal|test|simulated)\s+)*"
_WAVE = r"wavelength"
_TEMP = r"temperature"
_ZERO = r"(?:\bzero(?:ing|ed)?\b|\b(?:perform|apply) (?:a |the )?zero adjustment\b)"
_READ = (r"\b(?:read(?:ing)?|record(?:ing)?|note|observe|capture)\s+"
         r"(?:(?:the|a|its|final|simulated|instrument|device|optical|reference|thermometer|"
         r"temperature|current|measured|resulting|stable|wavelength|value|on|shown|digital)\s+)*"
         r"(?:display(?:ed)?|readout|screen|reading|indication)\b|\bread(?=\s*(?:$|[,.;]))")
_ACTION = re.compile(
    rf"(?P<zero>{_ZERO})|(?P<read_display>{_READ})|"
    rf"(?P<set_wavelength>\b{_SET}\s+{_PARAM}{_WAVE}\b)|"
    rf"(?P<set_temperature>\b{_SET}\s+{_PARAM}{_TEMP}\b)|"
    rf"(?P<set_quantity>\b{_SET}\s+(?:it\s+)?(?:to\s+)?(?={_NUMBER}\s*{_UNIT}))"
)
_EXPECTED = {"set_wavelength": "nm", "set_temperature": "C"}
_CAUTION = re.compile(r"\b(?:not|never|cannot|can't|mustn't|don't|avoid|unsupported|forbidden|"
                      r"prohibited|optional(?:ly)?|alternatively|instead|unless|if|or|either|before|after)\b")
_UNREPRESENTABLE = re.compile(r"\b(?:wait|hold|repeat|loop|power|install|remove|connect|disconnect|"
                              r"immerse|stir|pressurize|inject|heat|cool|switch|warm up|calibrate|"
                              r"export|upload|save|clean|mix|transfer|turn on|turn off|twice|thrice)\b")


def _unit(text):
    return "nm" if text.startswith(("nm", "nano")) else "C"


def _number(text):
    n = float(text)
    if not math.isfinite(n):
        raise ValueError
    return int(n) if n.is_integer() else n


def _sentences(text):
    # Keep decimals intact and treat numbered list markers as separators.
    text = re.sub(r"(?:^|(?<=\s))(?:step\s+)?\(?\d+[.):]\s+", "\n", _normalize(text))
    parts = re.split(r"[;\n]+|\.(?=\s|$)", text)
    return [re.sub(r"^[-*•]\s+", "", s.strip()) for s in parts if s.strip()]


def _sop_steps(source, goal, model):
    steps = []
    heading_words = _words(goal + " " + model + " " + source.family) | _STOP
    heading_words.update({"first", "second", "third", "last", "start", "begin", "by", "now",
                          "the", "objective", "title", "scope", "method", "instructions"})
    for sentence in _sentences(source.text):
        if ":" in sentence:
            prefix, tail = sentence.split(":", 1)
            if prefix.strip() in ("goal", "purpose", "objective", "title", "scope"):
                if steps or (_ACTION.search(tail) and not _words(tail) <= heading_words):
                    raise ValueError
                continue
            if _words(prefix) <= heading_words:
                sentence = tail.strip()
        if _CAUTION.search(sentence) or _UNREPRESENTABLE.search(sentence):
            raise ValueError
        clauses = re.split(r",|\b(?:and\s+then|then|next|finally|and)\b|→|->", sentence)
        for clause in clauses:
            clause = clause.strip(" \t:-")
            if not clause or clause in {"first", "second", "third", "last"}:
                continue
            found = list(_ACTION.finditer(clause))
            if not found:
                if steps or not _words(clause) <= heading_words:
                    raise ValueError
                continue
            if len(found) != 1:
                raise ValueError
            match = found[0]
            if not _words(clause[:match.start()]) <= heading_words:
                raise ValueError
            cmd = match.lastgroup
            amounts = list(_AMOUNT.finditer(clause))
            if cmd in ("zero", "read_display"):
                if amounts or re.search(r"\b\d+\b", clause[match.end():]):
                    raise ValueError
                steps.append((cmd, None, None))
                continue
            if len(amounts) != 1 or amounts[0].start() < match.end():
                raise ValueError
            amount = amounts[0]
            # Reject ranges, missing units and alternative bare numeric targets.
            rest = clause[match.end():amount.start()] + " " + clause[amount.end():]
            if re.search(r"\d|[<>±≈~]|\b(?:about|approximately|between|above|below|at least|at most)\b", rest):
                raise ValueError
            unit = _unit(amount[2])
            if cmd == "set_quantity":
                cmd = "set_wavelength" if unit == "nm" else "set_temperature"
            if _EXPECTED[cmd] != unit:
                raise ValueError
            steps.append((cmd, _number(amount[1]), unit))
    if not steps:
        raise ValueError
    return steps


_RANGE = re.compile(rf"(?<![\w.])({_NUMBER})\s*({_UNIT})?\s*(\.\.|[-–—]|through|to|and)"
                    rf"\s*({_NUMBER})\s*({_UNIT})?")
_MENTION = {
    "zero": re.compile(_ZERO),
    "read_display": re.compile(rf"{_READ}|\bdisplay (?:read(?:ing)?s?|can be read)\b|\breadable display\b"),
    "set_wavelength": re.compile(r"\bwavelengths?\b"),
    "set_temperature": re.compile(r"\btemperatures?\b|\bthermometer setpoints?\b"),
}
_DENY = re.compile(r"\b(?:not|no|never|cannot|can't|unable|unsupported|unavailable|disabled|"
                   r"forbidden|prohibited|disallowed|doesn't|mustn't|don't|without)\b")
_CAPABILITY = re.compile(r"\b(?:supports?|supported|available|allowed|allows?|permitted|permits?|"
                         r"can|capable|capabilities|controls?|functions?|commands?|buttons?|operations?|"
                         r"features?|enabled|possible|provides?)\b")
_NON_SETTING = re.compile(r"\b(?:storage|stored|shipping|transport|survival|ambient conditions|"
                          r"measuring range|measurement range|sensor range)\b")
_UNPARSED_LIMIT = re.compile(r"[<>±≈~]|\b(?:except|excluding|exclusive|increment|increments|"
                             r"resolution|intervals|multiples|tolerance)\b")
_BOUND = re.compile(
    rf"\b(min(?:imum)?|max(?:imum)?|at least|at most|up to|no more than|no less than|"
    rf"must not exceed|less than|greater than|below|above)\b"
    r"(?:\s+(?:allowed|operating|supported|wavelength|temperature|value|is|of)){0,4}"
    rf"\s*[:=]?\s*({_NUMBER})\s*({_UNIT})"
)


@dataclass
class Assertion:
    source: Source
    command: str
    allowed: bool = True
    capable: bool = False
    # Each constraint from the edition must hold for the SOP's exact value.
    bounds: list = field(default_factory=list)
    settings: list = field(default_factory=list)

    def permits(self, value):
        if not self.allowed:
            return False
        if value is None:
            return True
        return (all((value > lo or (lc and value == lo)) and
                        (value < hi or (hc and value == hi)) for lo, lc, hi, hc in self.bounds)
                and all(value in settings for settings in self.settings))

    def witnesses(self, value):
        return self.capable and (value is None or bool(self.bounds or self.settings))


def _manual_instruction(cmd, clause):
    # A documented imperative can establish capability without the word "supports".
    for part in re.split(r"\s*(?:,|:|\band\b|\bthen\b)\s*", clause):
        m = _ACTION.match(part.strip())
        if m and m.lastgroup == cmd:
            if cmd != "zero" or re.fullmatch(
                r"zero(?:\s+(?:(?:the|this|a|simulated|optical)\s+)*(?:reference|instrument|"
                r"device|meter|display|unit|thermometer))?", part.strip()
            ):
                return True
    return False


def _assertions(source):
    claims = {}
    for sentence in _sentences(source.text):
        # Split negated capabilities from their positive neighbors.
        for clause in re.split(r"\bbut\b|,\s*(?=(?:no|not|cannot|does not)\b)", sentence):
            ranges = list(_RANGE.finditer(clause))
            amounts = list(_AMOUNT.finditer(clause))
            bounds = list(_BOUND.finditer(clause))
            polarity = _DENY.search(_BOUND.sub("", clause)) is None
            for cmd, matcher in _MENTION.items():
                unit = _EXPECTED.get(cmd)
                mentioned = matcher.search(clause)
                # A dimensioned range can supply a limit independently of the
                # sentence that names the control.
                relevant_range = []
                for m in ranges:
                    units = {_unit(u) for u in (m[2], m[5]) if u}
                    if units == {unit} and (m[3] != "and" or "between" in clause[:m.start()]):
                        relevant_range.append(m)
                relevant_bound = [b for b in bounds if _unit(b[3]) == unit]
                if unit and _NON_SETTING.search(clause):
                    # Environmental limits cannot validate a commanded setpoint.
                    continue
                if not (mentioned or relevant_range or relevant_bound):
                    continue
                capability = bool(mentioned and (_CAPABILITY.search(clause) or _manual_instruction(cmd, clause)))
                if unit and mentioned and (relevant_range or relevant_bound):
                    capability = True
                restricted = bool(unit and re.search(r"\bread[ -]only\b", clause))
                if not (capability or relevant_range or relevant_bound or restricted or not polarity):
                    continue
                claim = claims.setdefault(cmd, Assertion(source, cmd))
                claim.capable |= capability
                if not polarity or restricted or (unit and _UNPARSED_LIMIT.search(clause)):
                    claim.allowed = False
                if unit is None:
                    continue
                for m in relevant_range:
                    claim.bounds.append((_number(m[1]), True, _number(m[4]), True))
                for b in relevant_bound:
                    kind, n = b[1], _number(b[2])
                    if kind in ("min", "minimum", "at least", "no less than", "greater than", "above"):
                        claim.bounds.append((n, kind not in ("greater than", "above"), math.inf, False))
                    else:
                        claim.bounds.append((-math.inf, False, n, kind not in ("less than", "below")))
                if not relevant_range and not relevant_bound and mentioned:
                    if amounts and re.search(r"\b(?:supports?|allowed|permits?|permitted|settings?|setpoints?|set|only)\b", clause):
                        settings = {_number(m[1]) for m in amounts if _unit(m[2]) == unit}
                        if settings:
                            claim.settings.append(settings)
    return claims.values()


def solve(request):
    """Return an ordered draft with one SOP citation and one manual citation per step."""
    abstain = {"status": "needs_input", "steps": []}
    try:
        sources = _sources(request)
        sop = _resolve(request["goal"], request["model"], [s for s in sources if s.kind == "sop"])
        if sop is None:
            return abstain
        steps = _sop_steps(sop, request["goal"], request["model"])
        ledger = defaultdict(dict)
        for source in sources:
            if source.kind == "manual":
                for claim in _assertions(source):
                    ledger[claim.command, source.model][source.id] = claim
        draft = []
        for cmd, value, unit in steps:
            claims = (ledger[cmd, request["model"]] or ledger[cmd, "*"]).values()
            witnesses = [c.source.id for c in claims if c.witnesses(value)]
            if not witnesses or not all(c.permits(value) for c in claims):
                return abstain
            witness = min(witnesses)
            draft.append({"command": cmd, "value": value, "unit": unit,
                          "citations": [sop.id, witness]})
        return {"status": "draft", "steps": draft}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return abstain
