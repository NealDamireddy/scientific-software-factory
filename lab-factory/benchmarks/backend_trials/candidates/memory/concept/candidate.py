"""Offline retrieval over a revision-filtered reference collection."""

import math
import re
import unicodedata
from collections import Counter


# The first spelling names the concept. Multiword aliases consume the whole
# phrase so that e.g. "power cycle" does not count as evidence for a bicycle.
_CONCEPTS = (
    "home|homing|rehome|re homing|return to origin|return to zero|home position|find origin",
    "align|alignment|aligning|aligned|line up",
    "calibrate|calibrating|calibration|calibrated|recalibrate|recalibration",
    "verify|verification|validate|validation|checking|check|confirm",
    "repeatability|repeatable|reproducibility|reproducible",
    "drift|drifting|drifted|slowly shifts|slow shift|gradual shift|creep",
    "noise|noisy|jitter|jittery|fluctuation|fluctuations",
    "vibration|vibrating|vibrate|shaking|shake|shakes",
    "backlash|mechanical play|lost motion",
    "saturate|saturated|saturation|clipping|clipped",
    "overheat|overheating|overheated|too hot|excessive heat",
    "temperature|temp|thermal",
    "warmup|warm up|warming up|warmup time",
    "cooldown|cool down|cooling down",
    "restart|reboot|rebooting|restarting|power cycle|power cycling",
    "shutdown|shut down|power off|switch off|turn off|power down",
    "startup|start up|power on|power up|switch on|turn on",
    "estop|e stop|emergency stop|emergency halt|emergency shutdown",
    "disconnect|disconnected|disconnection|lost connection|connection lost",
    "connect|connecting|connection",
    "timeout|time out|timed out|timing out",
    "freeze|frozen|unresponsive|not responding|hangs|hanging",
    "error|fault|failure|failed|malfunction",
    "troubleshoot|troubleshooting|diagnose|diagnostic|diagnosis",
    "maintenance|maintain|maintaining|upkeep|servicing",
    "replace|replacement|replacing|swap out",
    "install|installation|installing",
    "remove|removal|removing",
    "configure|configuration|configuring|settings|configure settings",
    "adjust|adjustment|adjusting|tune|tuning",
    "clean|cleaning|cleaned|cleanse",
    "lubricate|lubrication|lubricating|grease|greasing",
    "tighten|tightening|retighten",
    "level|leveling|levelling",
    "move|motion|movement|moving|moved",
    "speed|velocity",
    "rotate|rotation|rotating|rotary",
    "position|positioning|positional",
    "travel limit|endstop|end stop|limit switch|travel limits|end of travel",
    "camera|imager",
    "image|imaging|picture|photo|photograph",
    "focus|focusing|focussing|focused|focal",
    "blur|blurry|blurred|out of focus",
    "brightness|intensity",
    "illumination|lighting",
    "acquire|acquisition|acquiring|capture|capturing",
    "sampling rate|sampling frequency|sample rate|sample frequency",
    "average|averaging|averaged|arithmetic mean",
    "offset|bias",
    "baseline|base line",
    "tare|taring|zero the balance|zero the scale",
    "stabilize|stabilise|stabilization|stabilisation|stabilizing|settling|settle",
    "measure|measurement|measuring|measured|reading",
    "duration|how long|length of time",
    "interval|how often|frequency of",
    "maximum|max|upper bound|upper limit|highest",
    "minimum|min|lower bound|lower limit|lowest",
    "tolerance|allowable deviation|permitted deviation",
    "threshold|cutoff|cut off",
    "export|exporting|save to file",
    "inventory|stock list",
    "identifier|serial number|serial no",
    "sop|standard operating procedure|procedure|protocol",
    "manual|handbook|user guide",
    "log|logbook|run log",
)

_STOP = set("""
    a about according actually an and any are as ask at be been being by can
    could describe details did do does document documentation documents during
    explain find for from get give guidance has have help how i if in information
    instructions into is it its know me model my need of on or our please provide
    record records reference references relevant should show some steps tell
    than that the their them there these they this those to up us use using want
    was we what when where which while who why will with would you your
    equipment instrument device system machine unit
""".split())

_BROAD = {
    "adjust", "calibrate", "configure", "duration", "error", "interval",
    "log", "maintenance", "manual", "maximum", "measure", "minimum",
    "move", "position", "replace", "run", "set", "setting", "setup",
    "sop", "test", "troubleshoot", "verify",
}
_KINDS = {"manual", "sop", "log"}


def _words(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[^\W_]+", value)


def _singular(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


_ALIASES = {}
for _group in _CONCEPTS:
    _name, *_variants = _group.split("|")
    for _variant in [_name, *_variants]:
        _ALIASES[tuple(_words(_variant))] = _name
_MAX_ALIAS = max(map(len, _ALIASES))


def _features(value, model_words):
    words = _words(value)
    features = []
    raw = set()
    i = 0
    while i < len(words):
        if model_words and words[i:i + len(model_words)] == model_words:
            i += len(model_words)
            continue
        for width in range(min(_MAX_ALIAS, len(words) - i), 0, -1):
            phrase = tuple(words[i:i + width])
            concept = _ALIASES.get(phrase)
            if concept is not None:
                raw.add(phrase)
                features.append(concept)
                i += width
                break
        else:
            word = words[i]
            if word not in _STOP:
                singular = _singular(word)
                features.append(_ALIASES.get((singular,), singular))
                raw.add((word,))
            i += 1
    return features, raw


def _eligible(request):
    current = {}
    for doc in request["documents"]:
        if doc["model"] not in (request["model"], "*") or doc["revision"] > request["as_of"]:
            continue
        family = doc["id"].rsplit("@", 1)[0]
        priority = (doc["revision"], doc["model"] == request["model"])
        if family not in current or priority > current[family][0]:
            current[family] = (priority, doc)
    return [doc for _, doc in current.values()]


def solve(request):
    """Return up to three current IDs supported by the query's concepts."""
    model = _words(request["model"])
    query, literal_query = _features(request["query"], model)
    terms = set(query) - _KINDS
    if not terms:
        return []

    corpus = []
    frequency = Counter()
    for doc in _eligible(request):
        tokens, literals = _features(doc["text"], model)
        concepts = set(tokens)
        kinds, _ = _features(doc["kind"], [])
        corpus.append((doc["id"], tokens, concepts, literals, set(kinds)))
        frequency.update(concepts)
    if not corpus:
        return []

    # Unseen query terms still consume part of the evidence budget. Cap IDF
    # so that a rare (or unknown) word cannot dominate a short collection.
    weights = {
        t: (0.55 if t in _BROAD else 1.0)
        * (1 + min(1.5, math.log((1 + len(corpus)) / (1 + frequency[t]))))
        for t in terms
    }
    total = sum(weights.values())
    ranked = []
    for doc_id, tokens, concepts, literals, kinds in corpus:
        matches = terms & concepts
        if not matches or (terms - _BROAD and not matches - _BROAD):
            continue
        coverage = sum(weights[t] for t in matches) / total
        if coverage < 0.54 or (len(matches) == 1 and len(terms) > 2):
            continue
        # Prefer references discussing the concepts together. Only locations
        # of query terms enter this window, and repeated terms count once.
        nearby = Counter()
        local = best_local = 0.0
        for i, token in enumerate(tokens):
            if i >= 24 and tokens[i - 24] in matches:
                expired = tokens[i - 24]
                nearby[expired] -= 1
                if not nearby[expired]:
                    local -= weights[expired]
            if token in matches:
                if not nearby[token]:
                    local += weights[token]
                nearby[token] += 1
                best_local = max(local, best_local)
        literal = len(literals & literal_query) / max(1, len(literal_query))
        kind_bonus = 0.07 if kinds & set(query) & _KINDS else 0.0
        score = coverage + 0.15 * best_local / total + 0.05 * literal + kind_bonus
        ranked.append((score, doc_id, matches))

    ranked.sort(key=lambda row: (-row[0], row[1]))
    if not ranked:
        return []
    top, _, evidence = ranked[0]
    close = [row for row in ranked if row[0] >= top - 0.20]
    if len(close) > 1:
        if terms <= _BROAD and len(terms) == 1:
            return []
        for score, _, other in close[1:]:
            if top - score < 0.09 and evidence - other and other - evidence:
                return []
    return [doc_id for _, doc_id, _ in close[:3]]
