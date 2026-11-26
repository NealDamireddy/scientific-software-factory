"""A closed, citation-preserving grammar for simulated instrument drafts."""

import math
import re
import unicodedata
from typing import NamedTuple


class EvidenceError(ValueError):
    """The evidence does not determine one supported draft."""


class Action(NamedTuple):
    command: str
    value: float | None
    unit: str | None


def _normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return text.translate(str.maketrans({"−": "-", "–": "-", "—": "-", "_": " "}))


def _edition(value):
    match = re.fullmatch(r"(?:rev(?:ision)?[ .-]*|[vr])?(\d+(?:[.-]\d+)*)",
                         str(value).strip(), re.I)
    if not match:
        raise EvidenceError
    return tuple(int(part) for part in re.split(r"[.-]", match[1]))


def _editions(documents, model, cutoff):
    # First restrict by snapshot and applicability, then choose within a family.
    groups = {}
    for doc in documents:
        if doc["model"] not in (model, "*") or doc["kind"] not in ("sop", "manual"):
            continue
        edition = _edition(doc["revision"])
        if edition > cutoff:
            continue
        family, sep, suffix = doc["id"].rpartition("@")
        if not family or not sep or not suffix:
            raise EvidenceError
        group = groups.setdefault((doc["kind"], family), [])
        group.append(((doc["model"] == model, edition), doc))

    result = {"sop": [], "manual": []}
    for (kind, _), choices in groups.items():
        highest = max(rank for rank, _ in choices)
        selected = [d for rank, d in choices if rank == highest]
        if any(d != selected[0] for d in selected[1:]):
            raise EvidenceError
        result[kind].append(selected[0])
    return result


_NOISE = set("""a an the to of for on in at by with my our this using please run
perform conduct carry out draft prepare generate create simulate simulated simulation
procedure sop steps how do i need want and instrument model is goal task purpose
check test routine protocol workflow verify verification""".split())
_SYNONYM = {"thermometer": "temperature", "thermal": "temperature", "temp": "temperature",
            "reading": "read", "displayed": "display", "references": "reference"}


def _tokens(text, model):
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    ignore = _NOISE | set(re.findall(r"[a-z0-9]+", _normalize(model)))
    return {_SYNONYM.get(w, w) for w in words if w not in ignore}


def _goal_score(doc, goal, model):
    wanted = _tokens(goal, model)
    if not wanted:
        return 0
    family = doc["id"].rsplit("@", 1)[0]
    opening = re.split(r"[.;\n]", doc["text"], maxsplit=1)[0]
    labels = re.findall(r"(?:goal|title|task|purpose|objective)\s*:\s*([^.;\n]+)",
                        doc["text"], re.I)
    if any(wanted <= _tokens(part, model) for part in [family, opening, *labels]):
        return 2
    return int(wanted <= _tokens(family + " " + doc["text"], model))


NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
NM = r"(?:nm|nanomet(?:er|re)s?)"
CELSIUS = r"(?:°\s*c(?:elsius)?|(?:deg(?:ree)?s?\.?\s*)?c(?:elsius)?)"
UNIT = rf"(?:{NM}|{CELSIUS})"
ARTICLE = r"(?:(?:the|a|an|its)\s+)?"
NOUN = r"(?:simulated |digital |optical |reference |thermometer |temperature |instrument |front[ -]panel )*"
ZERO_OBJECT = rf"{ARTICLE}{NOUN}(?:reference|standard|channel|instrument|display|meter|sensor|device|baseline|reader|thermometer|unit)"
READ_OBJECT = rf"{ARTICLE}{NOUN}(?:display|readout|reading|displayed (?:value|reading|temperature)|display (?:value|reading)|value)"
AXIS = r"(?:(?:optical |reference |target )?wavelength|(?:target |display )?temperature|temp|(?:temperature )?set[ -]?point|thermometer(?: display)?)"
SET_VERB = r"(?:set|adjust|select|program|choose|dial(?: in)?|tune|use)"
SET_ACTION = re.compile(
    rf"{SET_VERB}\s+(?:{ARTICLE}(?P<axis>{AXIS})\s+)?"
    rf"(?:(?:to|at|of|=)\s*)?{ARTICLE}(?P<value>{NUMBER})\s*(?P<unit>{UNIT})"
    rf"(?:\s+(?P<suffix>wavelength|temperature|set[ -]?point))?"
)
ZERO_ACTION = re.compile(rf"(?:press|push)\s+{ARTICLE}zero(?: button| key)?|(?:zero|blank|tare)(?:\s+{ZERO_OBJECT})?|(?:perform\s+{ARTICLE}zero(?:ing)?(?: operation)?)")
READ_ACTION = re.compile(rf"read(?:\s+{READ_OBJECT})?|(?:record|observe|note|capture)\s+{READ_OBJECT}|take\s+{ARTICLE}(?:display )?reading")
ORDER = r"(?:(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|next|then|finally|last(?:ly)?|afterwards|subsequently)\b[\s,:-]*)"
LABEL = r"(?:goal|title|task|purpose|objective|procedure|protocol|sop|method|instructions|sequence|steps?|order)"
UNCERTAIN = re.compile(r"\b(?:if|unless|optionally|optional|alternatively|either|or|may|might|approximately|about|until|before|repeat|never|not|cannot|instead)\b")


def _action(clause):
    if ZERO_ACTION.fullmatch(clause):
        return Action("zero", None, None)
    if READ_ACTION.fullmatch(clause):
        return Action("read_display", None, None)
    m = SET_ACTION.fullmatch(clause)
    if not m:
        raise EvidenceError
    optical = bool(re.fullmatch(NM, m["unit"]))
    for axis in (m["axis"], m["suffix"]):
        if axis and (("wavelength" in axis and not optical) or
                     (("temp" in axis or "thermometer" in axis) and optical)):
            raise EvidenceError
    value = float(m["value"])
    if not math.isfinite(value):
        raise EvidenceError
    return Action("set_wavelength", value, "nm") if optical else Action("set_temperature", value, "C")


def _sentences(text):
    return re.split(r"[;\n]+|\.(?=\s|$)", text)


def _procedure(doc, goal, model):
    actions = []
    for sentence in _sentences(_normalize(doc["text"])):
        sentence = sentence.strip(" \t.*-")
        if not sentence or re.fullmatch(r"(?:step\s*)?\d+[):]?", sentence):
            continue
        # A labelled goal is metadata, even if it contains a command verb.
        heading = re.match(r"^(?:goal|title|task|purpose|objective)\s*:\s*(.*)", sentence)
        if heading:
            fields = re.split(r"\b(?:steps?|procedure|instructions)\s*:\s*", heading[1], maxsplit=1)
            if len(fields) == 2:
                sentence = fields[1]
            elif not re.search(r"[,→:]|->|\bthen\b", heading[1]):
                continue
            else:
                sentence = heading[1]
        sentence = re.sub(rf"^(?:{LABEL})\s*:\s*", "", sentence)
        sentence = re.sub(r"^(?:step\s*)?\d+[):.]\s*", "", sentence)
        if not sentence:
            continue
        # A goal heading or introductory purpose clause may precede instructions.
        intro = re.match(r"^(.+?)[:,]\s*(.+)$", sentence)
        if intro and not actions and _tokens(goal, model) == _tokens(intro[1], model):
            if not re.search(r"\b(?:zero|set|read|adjust|select)\b", intro[1]):
                sentence = intro[2]
        if (not actions and _tokens(goal, model) == _tokens(sentence, model)
                and not re.search(rf"\b(?:zero|blank|tare|read|record|{SET_VERB})\b", sentence)
                and not UNCERTAIN.search(sentence)):
            continue
        after = re.fullmatch(r"after (setting|zeroing|reading) (.+?),\s*(.+)", sentence)
        if after:
            verb = {"setting": "set", "zeroing": "zero", "reading": "read"}[after[1]]
            sentence = f"{verb} {after[2]}, {after[3]}"
        if UNCERTAIN.search(sentence):
            raise EvidenceError
        parts = re.split(r"\s*(?:,|->|→)\s*|\s+\b(?:and(?:\s+then)?|then|followed by)\b\s+", sentence)
        for part in parts:
            part = re.sub(r"^and\s+", "", part.strip())
            part = re.sub(rf"^(?:{ORDER})+", "", part).strip()
            if part:
                actions.append(_action(part))
    if not actions:
        raise EvidenceError
    return actions


# Match typed capability expressions in an assertion, an imperative, or a
# capability list. A number or instrument noun alone is not a permission.
_ZERO_MENTION = re.compile(
    rf"\b(?:zero(?:ing|ed)|(?:zero|blank|tare)\s+{ZERO_OBJECT}|"
    r"(?:zero|blank|tare)(?=\s*(?:$|[,:(]|and\b|or\b|is\b|command|function|button|key|operation)))\b"
)
_READ_MENTION = re.compile(
    rf"\b(?:read(?:s|ing)?\s+{READ_OBJECT}|display\s+read(?:s|ing|out)?|"
    r"display (?:can|may|cannot|can't) be read|readout|"
    r"read(?=\s*(?:$|[,:(]|and\b|or\b|is\b|command|function)))\b"
)
_ASSERTION = re.compile(r"\b(?:supports?|supported|allows?|allowed|permits?|permitted|enables?|"
                        r"available|capable|capabilit(?:y|ies)|commands?|functions?|operations?|"
                        r"accepts?|can|may|able to|provides?|features?)\b")
_NEG = re.compile(r"\b(?:not|no|never|cannot|can.t|prohibit\w*|unsupported|disabled|unavailable|"
                  r"forbid\w*|except|excluding|lacks?|without|optional|unless|if)\b")
_RANGE = re.compile(
    rf"(?<![\w.+-])({NUMBER})\s*({UNIT}\b)?\s*(-|to|through|and|\.\.)\s*"
    rf"({NUMBER})(?![\d.])\s*({UNIT}\b)?"
)
_CONTROL = re.compile(r"\b(?:set(?:s|ting|tings|table|points?)?|select(?:s|ed|able|ion)?|"
                      r"adjust(?:able|ed|ment)?|programmable|tune|dial)\b")
_CONTEXT_RANGE = re.compile(r"(?:the )?(?:(?:allowed|permitted|supported|valid|selectable) )?"
                            r"(?:wavelengths?|temperatures?|set[ -]?points?)(?: range| limits?)?\b")
_ENVIRONMENT = re.compile(r"\b(?:ambient|environment|storage|detects?|detection|measures?|"
                          r"measurement|accuracy|resolution|historical|example)\b")
_QUALIFIER = re.compile(r"\b(?:increments?|intervals?|steps?|multiples?|exclusive|except|"
                        r"excluding|strictly|above|below|greater|less)\b")
_RESTRICTION = re.compile(r"\b(?:minimum|maximum|at least|at most|up to|limited to|only|limit)\b")


def _limits(sentence, axis, unit):
    """Read a continuous setting interval. Both endpoints use the same unit."""
    ranges = []
    has_axis = re.search(rf"\b(?:{axis})s?\b", sentence)
    if not has_axis and re.search(r"\b(?:wavelength|temperature|thermometer|thermal)s?\b", sentence):
        return ranges
    for m in _RANGE.finditer(sentence):
        if m[3] == "and" and not re.search(r"\bbetween\s*$", sentence[:m.start()]):
            continue
        if not (m[2] or m[5]):
            continue
        # Reject an unrecognized unit after the second endpoint.
        if not m[5] and re.match(r"(?:°|[a-zμµ]+\b)", sentence[m.end():]):
            continue
        if any(u and not re.fullmatch(unit, u) for u in (m[2], m[5])):
            continue
        if _ENVIRONMENT.search(sentence) and not _CONTROL.search(sentence[:m.start()]):
            continue
        # Bare ranges may complete a separately asserted setting capability.
        scoped = has_axis or _CONTROL.search(sentence) or re.match(
            r"(?:the )?(?:(?:permitted|valid|allowed|supported) )?(?:range|limits?)\b", sentence)
        if scoped:
            ranges.append((float(m[1]), float(m[4])))
    return ranges


def _numeric_support(sentences, action):
    axis, unit = (("wavelength", NM) if action.unit == "nm"
                  else ("temperature|thermal|thermometer", CELSIUS))
    seen = allowed = False
    limits = []
    for sentence in sentences:
        bounds = _limits(sentence, axis, unit)
        named = re.search(rf"\b(?:{axis})s?\b", sentence)
        quantity = re.search(rf"{NUMBER}\s*{unit}\b", sentence)
        restriction = _RESTRICTION.search(sentence)
        if not (named or bounds or (quantity and restriction)):
            continue
        seen = True
        if _NEG.search(sentence) or _QUALIFIER.search(sentence):
            return False
        if _ENVIRONMENT.search(sentence) and not bounds:
            continue
        if (quantity or (restriction and re.search(NUMBER, sentence))) and not bounds:
            # An unparsed numeric restriction could invalidate the setting.
            return False
        limits.extend(bounds)
        if _CONTROL.search(sentence) or (bounds and _CONTEXT_RANGE.match(sentence)):
            allowed = True
        elif bounds and named and _ASSERTION.search(sentence):
            allowed = True
    if not seen:
        return None
    return allowed and bool(limits) and all(lo <= action.value <= hi for lo, hi in limits)


def _manual_support(doc, action):
    """Return None for silence, False for insufficient/conflicting evidence."""
    sentences = [s.strip() for s in _sentences(_normalize(doc["text"]))]
    if action.unit:
        return _numeric_support(sentences, action)
    mention = _ZERO_MENTION if action.command == "zero" else _READ_MENTION
    supported = None
    for sentence in sentences:
        match = mention.search(sentence)
        if match:
            if _NEG.search(sentence):
                return False
            supported = bool(supported or _ASSERTION.search(sentence) or match.start() == 0)
    return supported


def _cite(action, manuals, model):
    evidence = [(doc, _manual_support(doc, action)) for doc in manuals]
    for scope in (model, "*"):
        records = [(doc, supports) for doc, supports in evidence
                   if doc["model"] == scope and supports is not None]
        if records:
            if len(records) != 1 or not records[0][1]:
                raise EvidenceError
            return records[0][0]["id"]
    raise EvidenceError


def solve(request):
    try:
        model, goal = request["model"], request["goal"]
        if not model.strip() or model == "*" or not goal.strip():
            raise EvidenceError
        docs = _editions(request["documents"], model, _edition(request["as_of"]))
        ranked = []
        for sop in docs["sop"]:
            score = _goal_score(sop, goal, model)
            if score:
                ranked.append(((sop["model"] == model, score), sop))
        if not ranked:
            raise EvidenceError
        highest = max(rank for rank, _ in ranked)
        matches = [sop for rank, sop in ranked if rank == highest]
        if len(matches) != 1:
            raise EvidenceError
        sop = matches[0]
        steps = [{"command": action.command, "value": action.value, "unit": action.unit,
                  "citations": [sop["id"], _cite(action, docs["manual"], model)]}
                 for action in _procedure(sop, goal, model)]
        return {"status": "draft", "steps": steps}
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return {"status": "needs_input", "steps": []}
