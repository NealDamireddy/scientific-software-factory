"""Offline, revision-aware lexical reference retrieval."""

import math
import re
import unicodedata
from collections import Counter


_STOP = frozenset("""
    a about according all an and any are as at be both by can could describe describes
    do does document documents each edition editions every explain find for from get give
    has have how i in information instructions is it its latest look looking me
    list model multiple my need of on or our please provide record records reference references
    relevant requested retrieve return revision revisions say says search see should show some
    tell that the their there these this those to up us use used using version
    want we what when where which while who why will with would you
""".split())
_MULTIPLE = re.compile(r"\b(all|both|list|each|every|multiple|references|documents|records)\b")


def _terms(value):
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold())
    result = []
    for word in words:
        if word in _STOP:
            continue
        # Keep identifiers and numerical values intact. Fold common inflections
        # on ordinary words so a query for readings also finds a reading.
        if word.isascii() and word.isalpha():
            if len(word) > 4 and word.endswith("ies"):
                word = word[:-3] + "y"
            elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
                word = word[:-1]
            for suffix in ("ation", "ing", "ed"):
                if len(word) > len(suffix) + 2 and word.endswith(suffix):
                    word = word[:-3] if suffix == "ation" else word[:-len(suffix)]
                    break
            if len(word) > 4 and word.endswith("e"):
                word = word[:-1]
        result.append(word)
    return result


def _editions(request):
    newest = {}
    model = request["model"]
    for doc in request["documents"]:
        if doc["model"] not in (model, "*") or doc["revision"] > request["as_of"]:
            continue
        family = doc["id"].rsplit("@", 1)[0]
        order = (doc["revision"], doc["model"] == model)
        if family not in newest or order > newest[family][0]:
            newest[family] = (order, doc)
    return [(family, doc) for family, (_, doc) in newest.items()]


def solve(request):
    """Return up to three family editions supported by the query."""
    context = set(_terms(request["model"]))
    query = [t for t in _terms(request["query"]) if t not in context]
    wanted = set(query)
    if not wanted:
        return []

    query_pairs = set(zip(query, query[1:]))
    corpus = []
    frequency = Counter()
    for family, doc in _editions(request):
        fields = [_terms(doc["text"]), _terms(doc["kind"]), _terms(family)]
        counts = Counter(term for field in fields for term in field)
        pairs = {pair for field in fields for pair in zip(field, field[1:])}
        corpus.append((doc["id"], counts, sum(counts.values()), pairs))
        frequency.update(wanted.intersection(counts))
    if not corpus:
        return []

    size = len(corpus)
    mean_length = sum(row[2] for row in corpus) / size or 1
    idf = {t: math.log1p((size - frequency[t] + 0.5) / (frequency[t] + 0.5))
           for t in wanted}
    ranked = []
    for doc_id, counts, length, pairs in corpus:
        hits = wanted.intersection(counts)
        if len(hits) < min(2, len(wanted)) or len(hits) * 2 < len(wanted):
            continue
        # BM25 with k1=1.2 and b=0.65. Field boundaries count for phrases.
        norm = 1.2 * (0.35 + 0.65 * length / mean_length)
        score = sum(idf[t] * 2.2 * counts[t] / (counts[t] + norm) for t in sorted(hits))
        adjacent = len(query_pairs & pairs)
        score *= 1 + 0.4 * adjacent / max(1, len(query_pairs))
        score *= len(hits) / len(wanted)
        ranked.append((score, hits, adjacent, doc_id))
    if not ranked:
        return []

    ranked.sort(key=lambda row: (-row[0], row[3]))
    best_score, best_hits, best_pairs, _ = ranked[0]
    if len(ranked) > 1 and not _MULTIPLE.search(request["query"].casefold()):
        second_score, second_hits, second_pairs, _ = ranked[1]
        if len(wanted) == 1 or (
            second_score >= 0.92 * best_score
            and second_pairs == best_pairs
            and (best_hits != wanted or second_hits == best_hits)
        ):
            return []

    return [doc_id for score, hits, _, doc_id in ranked
            if score >= 0.45 * best_score and len(hits) * 3 >= len(best_hits) * 2][:3]
