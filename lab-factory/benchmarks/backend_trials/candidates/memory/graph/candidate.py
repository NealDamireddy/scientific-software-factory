"""Offline retrieval through instrument, source-kind, method and topic nodes."""

import math
import re
from collections import defaultdict


_STOP = set("""
a about according all an and any applicable apply appropriate are as at be best by
can could describe did do does document documents documentation during evidence explain
find for from get give has have help how i in information instructions into is it its
latest list look looking me model more my need of on or our per please provide
recorded reference references relevant requested required retrieve says see should
show some source sources specific specify support supports tell than that the their
them there these this those to use used using valid want we what whats when where
which with would you your instrument
""".split())

# Preserve topical distinctions while unifying common names for the same action.
_METHODS = {
    "align": "alignment aligning aligned",
    "calibrate": "calibration calibrating calibrated calibrations recalibration recalibrate",
    "measure": "measurement measurements measuring measured",
    "acquire": "acquisition acquisitions acquiring acquired",
    "clean": "cleaning cleaned",
    "inspect": "inspection inspecting inspected",
    "verify": "verification verifying verified",
    "maintain": "maintenance maintaining maintained",
    "initialize": "initialization initializing initialise initialisation",
    "scan": "scanning scans scanned",
    "stabilize": "stabilization stabilise stabilisation stabilizing stabilising",
    "troubleshoot": "troubleshooting",
}
_KINDS = {
    "sop": "sops procedure procedures protocol protocols",
    "manual": "manuals handbook handbooks",
    "report": "reports",
    "note": "notes",
    "log": "logs logbook",
    "record": "records",
    "checklist": "checklists",
    "specification": "specifications spec specs",
    "guide": "guides",
}
_ALIASES = {word: (role, name)
            for role, groups in (("method", _METHODS), ("kind", _KINDS))
            for name, aliases in groups.items()
            for word in [name, *aliases.split()]}


def _nodes(text, model):
    text = text.casefold()
    if model and model != "*":
        text = re.sub(r"(?<!\w)" + re.escape(model.casefold()) + r"(?!\w)", " ", text)
    text = re.sub(r"['’]s\b", "", text)
    text = re.sub(r"\bstandard[\s_-]+operating[\s_-]+procedures?\b", "sop", text)
    text = re.sub(r"\b(warm|start|set)[\s-]+up\b", r"\1up", text)
    nodes = []
    for word in re.findall(r"[^\W_]+", text):
        if word in _STOP:
            continue
        if word in _ALIASES:
            nodes.append(_ALIASES[word])
            continue
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        nodes.append(("topic", word))
    return nodes


def _editions(request, model):
    newest = {}
    for doc in request["documents"]:
        if doc["model"] not in (model, "*") or doc["revision"] > request["as_of"]:
            continue
        family = doc["id"].rsplit("@", 1)[0]
        if family not in newest or doc["revision"] > newest[family]["revision"]:
            newest[family] = doc
    return newest.values()


def solve(request):
    model = request["model"]
    query = _nodes(request["query"], model)
    if not query:
        return []

    # A posting is the set of editions reached from a typed concept node.
    links = defaultdict(set)
    descriptions = {}
    for doc in _editions(request, model):
        doc_id = doc["id"]
        body = _nodes(doc["text"], model)
        kinds = _nodes(doc["kind"], model)
        links["instrument", doc["model"]].add(doc_id)
        for node in kinds:
            links[node].add(doc_id)
            links["source", node[1]].add(doc_id)
        for node in body:
            links[node].add(doc_id)
        for left, right in zip(body, body[1:]):
            links["pair", left, right].add(doc_id)
        descriptions[doc_id] = set(body) | set(kinds)

    concepts = set(query)
    topical = {n for n in concepts if n[0] == "topic"}
    kinds = {n for n in concepts if n[0] == "kind"}
    pairs = set(zip(query, query[1:]))
    population = len(descriptions)
    weights = {n: 1 + math.log((population + 1) / (1 + len(links[n]))) for n in concepts}
    total = math.fsum(weights.values())
    scores = []
    eligible = links["instrument", model] | links["instrument", "*"]
    for doc_id in eligible:
        matches = concepts & descriptions[doc_id]
        if not matches or (topical and not topical & matches):
            continue
        if kinds and not any(doc_id in links["source", n[1]] for n in kinds):
            continue
        coverage = math.fsum(weights[n] for n in matches) / total
        if coverage < 0.57:
            continue
        phrase_hits = sum(doc_id in links["pair", a, b] for a, b in pairs)
        score = coverage + 0.24 * phrase_hits / max(1, len(pairs))
        score += 0.04 * (doc_id in links["instrument", model])
        scores.append((score, doc_id))

    scores.sort(key=lambda hit: (-hit[0], hit[1]))
    if not scores:
        return []
    # A bare method or source kind can name several unrelated records.
    # Require a unique candidate when nothing further qualifies that request.
    if len(concepts) == 1 and not topical and len(scores) > 1:
        return []
    floor = max(0.57, 0.72 * scores[0][0])
    return [doc_id for score, doc_id in scores[:3] if score >= floor]
