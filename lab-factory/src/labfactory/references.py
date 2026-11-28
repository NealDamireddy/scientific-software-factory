"""Search a versioned, bundled reference collection shared by the reviewer and MCP."""
from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

from .context import ContextError, canonical_digest, unique_fields

DATA = Path(__file__).with_name("reference_data")
KINDS = ("manual", "procedure", "paper")
STOP = frozenset("""a an the of this that for and or from with without using by to in on as
at is are do does i our we my how find determine identify measure check your experiment
study studies need can want use used what which would like me please measurement measurements
method methods sample samples find look sources suitable perform determine measuring quantify
validate investigate test compare calculate concentration content level amount an instruction
instructions operating guide manual documentation protocol""".split())


def _words(value):
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return re.findall(r"[^\W_]+", "".join(c for c in normalized if not unicodedata.combining(c)))


def _tokens(value, aliases):
    words = " " + " ".join(_words(value)) + " "
    for expression, replacement in aliases:
        words = words.replace(expression, replacement)
    return {word for word in words.split() if word not in STOP and len(word) > 1}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)


def _id(row, seen):
    identifier = row["id"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier) or identifier in seen:
        raise ValueError(f"Invalid or duplicate reference identifier {identifier}")
    return identifier


class ReferenceIndex:
    def __init__(self, directory):
        config = _read(directory / "search.json")
        aliases = [(" " + " ".join(_words(form)) + " ", " " + term + " ")
                   for term, forms in config["aliases"].items() for form in forms]
        self.aliases = sorted(aliases, key=lambda pair: -len(pair[0]))
        self.context_terms = set(config["context_terms"])
        self.models = {}
        for path in sorted(directory.glob("instruments*.json")):
            for item in _read(path):
                key = _id(item, self.models)
                if key == "all" or key.startswith("other-"):
                    raise ValueError(f"Reserved scope identifier {key}")
                self.models[key] = {**item, "scope": "model",
                                    "techniques": item.get("techniques", [item["technique"]])}
        families = {t for m in self.models.values() for t in m["techniques"]}
        self.labels = {t: config["technique_names"].get(t, t.upper()) for t in sorted(families)}
        self.family_terms = {t: _tokens(t, self.aliases) for t in families}
        self.scopes = {"all": {"id": "all", "scope": "all", "technique": "all",
                               "techniques": [], "manufacturer": "", "model": "All instruments", "aliases": []}}
        for t, name in self.labels.items():
            key = "other-" + t
            self.scopes[key] = {"id": key, "scope": "technique", "technique": t, "techniques": [t],
                                "manufacturer": "", "model": f"Any or unknown model · {name}", "aliases": []}
        self.scopes.update(sorted(self.models.items(), key=lambda item: (
            item[1]["technique"], item[1]["manufacturer"].casefold(), item[1]["model"].casefold())))
        self.examples = config["examples"]
        self.experiments = config.get("experiments", [])
        if any(ex["instrument"] not in self.scopes for ex in self.examples):
            raise ValueError("A reference example specifies an unknown instrument")
        # Concurrent hosted requests share these immutable tables. CPython's
        # connection-level statement cache cannot be shared by active cursors.
        self.db = sqlite3.connect(":memory:", check_same_thread=False, cached_statements=0)
        self.db.executescript("""
            CREATE TABLE sources(id TEXT PRIMARY KEY, kind TEXT, payload TEXT);
            CREATE TABLE terms(term TEXT, source_id TEXT, weight REAL, PRIMARY KEY(term, source_id));
            CREATE TABLE techniques(technique TEXT, source_id TEXT, PRIMARY KEY(technique, source_id));
        """)
        fingerprints = {}
        for path in sorted(directory.glob("*.json")):
            if path.name.startswith("instruments") or path.name == "search.json":
                continue
            for record in _read(path):
                key = _id(record, fingerprints)
                self._add(record, families)
                fingerprints[key] = canonical_digest(record)
        for experiment in self.experiments:
            techniques = set(experiment["techniques"])
            if not techniques or techniques - families or experiment["instrument"] not in self.models:
                raise ValueError(f"Unknown model or technique on {experiment['label']}")
            if not techniques.intersection(self.models[experiment["instrument"]]["techniques"]):
                raise ValueError(f"Example instrument does not support {experiment['label']}")
            for kind in ("procedure", "paper"):
                records = experiment[kind]
                if not records:
                    raise ValueError(f"No {kind} for {experiment['label']}")
                for key in records:
                    row = self.db.execute("SELECT payload FROM sources WHERE id=? AND kind=?", (key, kind)).fetchone()
                    if not row or not techniques.intersection(json.loads(row[0])["techniques"]):
                        raise ValueError(f"Invalid {kind} reference {key} on {experiment['label']}")
        self.counts = {k: 0 for k in KINDS}
        self.counts.update(self.db.execute("SELECT kind, count(*) FROM sources GROUP BY kind"))
        self.size = sum(self.counts.values())
        self.digest = canonical_digest({"sources": fingerprints, "models": self.models, "search": config})
        self.db.commit()
        self.db.execute("PRAGMA query_only=ON")

    def _add(self, record, families):
        key = record["id"]
        if record["kind"] not in KINDS or not set(record["instrument_ids"]) <= self.models.keys():
            raise ValueError(f"Invalid kind or model link on {key}")
        excluded = set(record.get("excluded_instrument_ids", []))
        prescribed = set(record.get("method_instrument_ids", []))
        if prescribed and (record["kind"] != "procedure" or prescribed - self.models.keys()):
            raise ValueError(f"Invalid method model on {key}")
        if excluded - self.models.keys() or excluded.intersection(prescribed.union(record["instrument_ids"])):
            raise ValueError(f"Invalid incompatible model on {key}")
        for field in ("title", "publisher", "version", "summary", "scope", "locator", "rights"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise ValueError(f"Missing {field} on {key}")
        url = urlsplit(record["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(f"Invalid source URL on {key}")
        techniques = set(record["techniques"])
        if not techniques or techniques - families:
            raise ValueError(f"Unknown technique on {key}")
        if record["kind"] == "manual" and not record["instrument_ids"]:
            raise ValueError(f"No documented instrument for {key}")
        row = {**record, "digest": canonical_digest(record)}
        self.db.execute("INSERT INTO sources VALUES (?,?,?)", (key, record["kind"], json.dumps(row)))
        self.db.executemany("INSERT INTO techniques VALUES (?,?)", [(t, key) for t in techniques])
        named = [self.models[i] for i in sorted(prescribed.union(record["instrument_ids"]))]
        model_text = " ".join(" ".join([m["manufacturer"], m["model"], *m["aliases"]]) for m in named)
        terms = Counter()
        for value, weight in ((record["summary"], 1), (record["title"], 4),
                              (" ".join(techniques), 3), (" ".join(record["topics"]), 5), (model_text, 5)):
            for word in _tokens(value, self.aliases):
                terms[word] += weight
        self.db.executemany("INSERT INTO terms VALUES (?,?,?)", [(t, key, w) for t, w in terms.items()])

    def candidates(self, scope):
        if scope["scope"] == "all":
            rows = self.db.execute("SELECT payload FROM sources ORDER BY id")
        else:
            techniques = scope["techniques"]
            places = ",".join("?" for _ in techniques)
            rows = self.db.execute(f"""SELECT payload FROM sources WHERE id IN
                (SELECT source_id FROM techniques WHERE technique IN ({places})) ORDER BY id""", techniques)
        return [json.loads(payload) for (payload,) in rows]

    def matches(self, words):
        scores = Counter()
        matched = {}
        for term in sorted(words):
            hits = self.db.execute("SELECT source_id, weight FROM terms WHERE term=?", (term,)).fetchall()
            rarity = 1 + math.log((self.size + 1) / (len(hits) + 1))
            for key, weight in hits:
                scores[key] += rarity * (1 + math.log(weight))
                matched.setdefault(key, []).append(term)
        return scores, matched

    def requested_models(self, q):
        """Resolve an explicit model number in a request for documentation."""
        terms = set(_words(q))
        if not terms.intersection({"manual", "manuals", "guide", "instructions", "documentation"}):
            return None
        numbers = {word for word in terms if any(c.isdigit() for c in word)}
        if not numbers:
            return None
        result = set()
        for key, model in self.models.items():
            names = " ".join([model["manufacturer"], model["model"], *model["aliases"]])
            model_terms = set(_words(names))
            named_number = any(any(c.isalpha() for c in token) for token in numbers)
            if numbers <= model_terms and (named_number or (terms - numbers).intersection(model_terms)):
                result.add(key)
        return result


@lru_cache(maxsize=1)
def _index():
    return ReferenceIndex(DATA)


def catalog():
    index = _index()
    return {"catalog_digest": index.digest, "counts": dict(index.counts), "examples": index.examples,
            "experiments": index.experiments,
            "technique_names": index.labels, "instruments": list(index.scopes.values())}


def source(identifier):
    row = _index().db.execute("SELECT payload FROM sources WHERE id=?", (identifier,)).fetchone()
    if not row:
        raise ContextError("Unknown reference source")
    return json.loads(row[0])


def model_for(text):
    """Return the catalog model id when exactly one model is named in the text, else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    haystack = " " + " ".join(_words(text)) + " "
    found = set()
    for key, item in _index().models.items():
        forms = [item["model"], f"{item['manufacturer']} {item['model']}", *item["aliases"]]
        if any(" " + " ".join(_words(form)) + " " in haystack for form in forms if _words(form)):
            found.add(key)
    return found.pop() if len(found) == 1 else None


def describe(instrument, q, findings):
    """Build a cited digest of precisely the supplied search or pinned result set."""
    if not findings:
        return "No indexed sources matched this objective and instrument selection.", []
    if not q:
        return f"Browsing {len(findings)} sources for {instrument['model']}. Enter an objective to narrow the results.", []
    counts = Counter(r["kind"] for r in findings)
    descriptions = [f"{counts[kind]} {label}{'' if counts[kind] == 1 else 's'}"
                    for kind, label in (("manual", "manual"), ("procedure", "published procedure"),
                                        ("paper", "research paper"))]
    overview = f"{descriptions[0]}, {descriptions[1]} and {descriptions[2]} in this selection."
    brief = []
    for kind, label in (("manual", "Instrument guidance"), ("procedure", "Published method"), ("paper", "Research evidence")):
        first = next((item for item in findings if item["kind"] == kind), None)
        if first:
            brief.append({"label": label, "text": first["summary"] + " " + first["scope"], "source_ids": [first["id"]]})
    if counts["manual"] == len(findings):
        overview += " Only instrument documentation matched. The collection supplies no matched experimental method or paper here."
    return overview, brief


def search(instrument="all", q=""):
    index = _index()
    if not isinstance(instrument, str) or instrument not in index.scopes:
        raise ContextError("Unknown reference instrument or technique")
    if not isinstance(q, str) or len(q) > 300:
        raise ContextError("The reference query must be text of at most 300 characters")
    try:
        q.encode("utf-8")
    except UnicodeEncodeError:
        raise ContextError("The reference query must be valid Unicode text") from None
    q = q.strip()
    scope = index.scopes[instrument]
    family_records = index.candidates(scope)
    excluded = {r["id"] for r in family_records if instrument in r.get("excluded_instrument_ids", ())}
    candidates = [r for r in family_records if r["id"] not in excluded]
    # Give the editor-selected methods and papers precedence for a published
    # experiment objective. Free-text searches continue to use term relevance.
    recommended = set()
    requirements = ""
    for experiment in index.experiments:
        if q.casefold() == experiment["q"].casefold() and (
            scope["scope"] == "all" or set(experiment["techniques"]).intersection(scope["techniques"])
        ):
            recommended.update(experiment["procedure"] + experiment["paper"])
            requirements = experiment["requirements"]
    words = _tokens(q, index.aliases)
    scores, matched = index.matches(words)
    named_families = {family for family, terms in index.family_terms.items() if terms <= words}
    within_scope = named_families if scope["scope"] == "all" else named_families.intersection(scope["techniques"])
    if within_scope:
        candidates = [r for r in candidates if within_scope.intersection(r["techniques"])]
    # A shared matrix such as water does not make a paper relevant to every
    # analyte in that matrix. Instrument family alone is equally unspecific.
    # In objectives such as "measure copper in water by colorimetry" the
    # analyte is the subject. The matrix or readout alone cannot answer it.
    subject = re.split(r"\b(?:in|using|with|by|against)\b", q, maxsplit=1, flags=re.IGNORECASE)[0]
    focus = (_tokens(subject, index.aliases) - index.context_terms) or (words - index.context_terms)
    if named_families:
        family_words = set().union(*(index.family_terms[t] for t in named_families))
        focus = focus - family_words or focus
    # If the flour records rule out a given oven, a shared word such as
    # "moisture" must not substitute a soil procedure for the flour query.
    unavailable = set()
    if excluded and focus and not recommended:
        excluded_terms = {t for key in excluded for t in matched.get(key, ())}
        available_terms = {t for r in candidates for t in matched.get(r["id"], ())}
        unavailable = (focus & excluded_terms) - available_terms
        if unavailable:
            candidates = []
    if focus:
        scores = Counter({key: score for key, score in scores.items() if focus.intersection(matched[key])})
    requested_models = index.requested_models(q)
    if requested_models is not None:
        candidates = [r for r in candidates if r["kind"] == "manual" and requested_models.intersection(r["instrument_ids"])]
    exact_scope = scope["scope"] == "model"
    # A plan can pair a matched study with the selected instrument's manual even
    # when that manual does not name the sample or analyte.
    has_evidence = any(r["kind"] != "manual" and (r["id"] in scores or r["id"] in recommended) for r in candidates)
    ranked = []
    for record in candidates:
        key = record["id"]
        exact = exact_scope and instrument in record["instrument_ids"]
        prescribed = exact_scope and instrument in record.get("method_instrument_ids", ())
        manual = record["kind"] == "manual"
        if exact_scope and manual and not exact:
            continue
        if q and key not in scores and key not in recommended and not (exact and manual and has_evidence):
            continue
        if manual and exact:
            match, reason = "instrument_manual", "The manufacturer lists the selected model in this guide."
        elif manual:
            match, reason = "catalog_manual", "The guide documents " + ", ".join(
                index.models[i]["model"] for i in record["instrument_ids"]) + "."
        elif exact:
            match, reason = "same_model_study", "The source reports using the selected model."
        elif prescribed:
            match, reason = "model_method", "The published procedure specifically lists the selected model."
        else:
            match = "related_method"
            reason = ("The source covers " + ", ".join(index.labels[t] for t in record["techniques"]) + ".")
            if exact_scope:
                reason += " Its evidence has no confirmed link to the selected model."
        if key in recommended:
            reason += " Selected for this experiment in the reference library."
        if q and key in matched:
            reason += " Indexed terms matched: " + ", ".join(matched[key]) + "."
        ranked.append((scores[key], exact or prescribed, {**record, "match": match, "reason": reason}))
    ranked.sort(key=lambda item: (item[2]["id"] not in recommended,
                                  not (item[1] and item[2]["id"] in recommended),
                                  -item[0], -item[1], item[2]["title"].casefold(), item[2]["id"]))
    findings = [row for _, _, row in ranked]
    overview, brief = describe(scope, q, findings)
    if unavailable:
        overview = "The indexed sources matching " + ", ".join(sorted(unavailable)) + " exclude this model."
    return {"instrument": scope, "query": q, "catalog_digest": index.digest, "findings": findings,
            "overview": overview, "brief": brief, "requirements": requirements,
            "incompatible_terms": sorted(unavailable)}
