"""Compile an explicitly applicable method into a cited, human-reviewed first draft."""

from decimal import Decimal
import re

from .checks import find_text_quantities
from .procedure_drafts import passages
from .units import UNIT_SPELLINGS, UnitError, convert_exact


# Plain observational and record-keeping steps can be quoted without prescribing device settings.
_OBSERVATION = re.compile(
    r"^(?:record|log|note|inspect|compare|check|verify|identify|label|review|save|export|"
    r"plot|calculate|report|document|read|observe|list|photograph|open|copy)\b", re.I
)
_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_UNITS = "|".join(map(re.escape, sorted(UNIT_SPELLINGS, key=len, reverse=True)))
_VALUE = re.compile(rf"({_NUMBER})\s*({_UNITS})(?!\w)")
_PREFIX = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+|Step\s+\d+\s*[:.]\s*)", re.I)
_COMMON = {"at", "from", "read", "record", "the", "and", "for", "with", "method", "using", "measure"}


def _goal_terms(experiment):
    return {t for t in re.findall(r"\w+", experiment.goal.casefold()) if len(t) > 2} - _COMMON


def applicable_methods(lab, experiment):
    terms = _goal_terms(experiment)
    return [d for d in (*experiment.documents, *lab.documents) if d.kind == "sop" and
            terms.intersection(re.findall(r"\w+", (d.title + " " + d.text).casefold()))]


def select_method(lab, experiment, method_id):
    documents = (*experiment.documents, *lab.documents)
    if method_id:
        matches = [d for d in documents if d.id == method_id]
        if len(matches) != 1:
            return None, f"Which unique pinned document contains the method? Could not resolve {method_id!r}."
        return matches[0], None
    matches = applicable_methods(lab, experiment)
    terms = _goal_terms(experiment)
    if len(matches) == 1 and sum(d.id == matches[0].id for d in documents) == 1:
        return matches[0], None
    if matches:
        return None, "Which method applies to this objective? Select a pinned document ID or supply its method passage."
    actions = [(device.id, command) for device in lab.instruments if device.id in experiment.instrument_ids
               for command in device.commands if command.required and terms.intersection(
                   set(re.findall(r"[^\W_]+", command.name.casefold())) - _COMMON)]
    if len(actions) == 1:
        device_id, command = actions[0]
        return None, (f"Which method passage specifies {', '.join(command.required)} for {command.name} "
                      f"on {device_id}? Supply the source and its complete instruction.")
    return None, f"Which method should be followed for “{experiment.goal}”? Supply the applicable method steps and their source."


def method_lines(lab, experiment, document):
    # The evidence service numbers chunks, including wrapped long lines. Never turn fragments of one
    # instruction into independent steps. Ask for a focused excerpt when the method cannot be copied intact.
    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    if len(lines) > 128 or any(len(line) > 700 or not line.isprintable() for line in lines):
        return [], "Can you supply a focused method excerpt with one complete instruction per line?"
    selected = [p for p in passages(lab, experiment) if p["document"] == document.id]
    return [{"document": p["document"], "passage": p["passage"]} for p in selected], None


def _command_matches(text, lab, experiment):
    explicit = re.match(r"^On ([^:]+):\s*", text, re.I)
    instruction = text[explicit.end():] if explicit else text
    found = []
    for instrument_id in experiment.instrument_ids:
        device = lab.instrument(instrument_id)
        if not device or (explicit and explicit[1] != instrument_id):
            continue
        for command in device.commands:
            words = re.split(r"[\s_]+", command.name)
            pattern = r"(?:[ _]+(?:the\s+)?)".join(map(re.escape, words))
            match = re.match(pattern + r"(?!\w)", instruction, re.I)
            if match:
                found.append((device, command, instruction[match.end():].strip()))
    return found


def _number(raw):
    if len(raw) > 40:
        return None
    decimal = Decimal(raw)
    numeric = int(decimal) if decimal == decimal.to_integral_value() else float(decimal)
    return numeric if Decimal(str(numeric)) == decimal else None


def _setting_parts(remainder, device, command):
    settings = []
    allowed = (*command.required, *command.optional)
    while remainder:
        remainder = re.sub(r"^(?:(?:at|to|for|with|and|using)\s+|,\s*)+", "", remainder, flags=re.I)
        name = None
        for candidate in sorted(allowed, key=len, reverse=True):
            pattern = r"[ _]+".join(map(re.escape, candidate.split("_")))
            match = re.match(pattern + r"(?!\w)\s*(?:=|:|of|to|at)?\s*", remainder, re.I)
            if match:
                name, remainder = candidate, remainder[match.end():]
                break
        match = _VALUE.match(remainder)
        if not match:
            return None, f"Which exact settings does the method prescribe for {command.name} on {device.id}?"
        number, unit = match.groups()
        numeric = _number(number)
        if numeric is None:
            return None, "What is the method's setting at the instrument's reported precision?"
        if not name:
            compatible = []
            for candidate in allowed:
                try:
                    convert_exact(numeric, unit, device.parameter(candidate).unit)
                    compatible.append(candidate)
                except UnitError:
                    continue
            if len(compatible) != 1:
                return None, f"Which named setting on {device.id} uses {number} {unit} for {command.name}?"
            name = compatible[0]
        settings.append({"parameter": name, "value": numeric, "unit": unit})
        remainder = remainder[match.end():].strip()
    missing = [p for p in command.required if p not in {s["parameter"] for s in settings}]
    if missing:
        return None, f"What {', '.join(missing)} does the method specify for {command.name} on {device.id}?"
    return settings, None


def _hand_amount(text):
    # Only convert an explicitly measured quantity; keep the operator's material and wording.
    match = re.fullmatch(rf"(Measure|Pipette)\s+({_NUMBER})\s*(uL|mL|L)\s+of\s+"
                         r"([\w -]+?)\.?", text, flags=re.I)
    if not match:
        return None
    verb, raw, unit, material = match.groups()
    value = _number(raw)
    if value is None or unit not in UNIT_SPELLINGS or value <= 0 or not material.strip():
        return None
    # Any conditions or additional actions need their own source-backed interpretation.
    if re.search(r"\b(?:and|or|if|unless|before|after|when|at|into|until|for|to)\b|\d", material, re.I):
        return None
    return {"text": f"{verb} the specified amount of {material}.",
            "amounts": [{"what": material, "unit": unit, "value": value}]}


def supplement_setting(lab, experiment, original, reply):
    """Recognize a literal setting answer only in the scope of an existing instrument command."""
    indexed = {(p["document"], p["passage"]): p["text"] for p in passages(lab, experiment)}
    instruction = _PREFIX.sub("", indexed[original["document"], original["passage"]]).rstrip(".")
    commands = _command_matches(instruction, lab, experiment)
    if len(commands) != 1:
        return None
    device, command, _ = commands[0]
    names = [r"[ _]+".join(map(re.escape, p.split("_"))) for p in (*command.required, *command.optional)]
    if not names:
        return None
    parameter = "|".join(names)
    text = indexed[reply["document"], reply["passage"]].strip().rstrip(".")
    match = re.fullmatch(rf"(?i:(?:use |the )?(?:({parameter})\s*(?:is|=|:|of|to|at)?\s*)?)"
                         rf"({_NUMBER}\s*(?:{_UNITS}))", text)
    if not match:
        return None
    setting = " ".join(part for part in match.groups() if part)
    return {**original, "supplements": [*original.get("supplements", []), {**reply, "setting": setting}]}


def build_candidate(lab, experiment, plan):
    indexed = {(p["document"], p["passage"]): p for p in passages(lab, experiment)}
    steps = []
    for index, ref in enumerate(plan):
        p = indexed[ref["document"], ref["passage"]]
        quote = p["text"]
        text = _PREFIX.sub("", quote).strip()
        step = {"citations": [p["document"]], "evidence": [
            {"document": p["document"], "passage": p["passage"], "quote": quote}
        ]}
        matches = _command_matches(text.rstrip("."), lab, experiment)
        if len(matches) > 1:
            return None, index, "Which instrument and command apply to this step? Use 'On instrument-id: command …'."
        if matches:
            device, command, remainder = matches[0]
            for supplement in ref.get("supplements", []):
                source = indexed[supplement["document"], supplement["passage"]]
                if source["document"] not in step["citations"]:
                    step["citations"].append(source["document"])
                step["evidence"].append({"document": source["document"], "passage": source["passage"],
                                         "quote": source["text"]})
                remainder = (remainder + " " + supplement["setting"]).strip()
            settings, question = _setting_parts(remainder, device, command)
            if question:
                return None, index, question
            step.update(text="", action={"instrument_id": device.id, "command": command.name, "settings": settings})
        elif (amount := _hand_amount(text)) is not None:
            step.update(amount)
        elif _OBSERVATION.match(text) and not find_text_quantities(text) and not re.search(r"\d\s*[°µμa-zA-Z%]", text):
            step["text"] = text
        else:
            return None, index, (
                f"How should passage {p['passage']} of {p['title']} be recorded? Supply the method's "
                "observational instruction or registered instrument command with its named settings and units."
            )
        steps.append(step)
    return {"steps": steps}, None, None
