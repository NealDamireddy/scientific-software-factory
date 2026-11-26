"""Black-box reference retrieval cases. IDs, scope and revision are public inputs."""

from copy import deepcopy
import json
from pathlib import Path


DATA = Path(__file__).resolve().parents[3] / "src/labfactory/reference_data"


def _doc(family, model, revision, words, kind="procedure"):
    return {"id": f"{family}@{revision}", "model": model, "revision": revision,
            "kind": kind, "text": words}


def _catalog_records():
    """Use committed catalog descriptions; revision 1 denotes the fixture edition."""
    ids = {
        "hanna-hi96800-manual", "oecd-fruit-soluble-solids",
        "agilent-caffeine-in-coffee-din-20481",
    }
    result = []
    for file in ("liquid-chromatography.json", "refractometry.json"):
        for record in json.loads((DATA / file).read_text(encoding="utf-8")):
            if record["id"] in ids:
                model = next(iter(record["instrument_ids"]), "*")
                text = " ".join([record["title"], record["summary"], record["locator"],
                                 *record["topics"]])
                result.append(_doc(record["id"], model, 1, text, record["kind"]))
    assert len(result) == len(ids)
    return result


def _cases():
    target = "ref-A"
    zero = _doc("prism", target, 1, "Zero check with water on the optical prism.")
    newer = _doc("prism", target, 4, "Zero reference for optical prism calibration.")
    off_model = _doc("second-prism", "ref-B", 2,
                     "Optical prism zero calibration. Prism calibration zero reference.")
    delayed = _doc("new-guide", target, 9, "Replacement optical prism zero calibration.")
    shared = _doc("bath", "*", 2, "Thermostatic bath temperature equilibration before reading.")
    paper = _doc("cones", target, 1, "Pine cone geometry and dry sample dimensions.", "paper")
    pool = [paper, delayed, newer, off_model, zero, shared]
    yield "pinned historical manual", pool, target, 2, "zero optical prism", [zero["id"]], {zero["id"]}
    yield "current manual and model exclusion", pool, target, 8, "optical prism zero calibration", [newer["id"]], {newer["id"]}
    yield "revision input order independent", list(reversed(pool)), target, 8, "optical prism zero calibration", [newer["id"]], {newer["id"]}
    yield "shared source eligible", pool, "ref-B", 8, "thermostatic bath temperature equilibration", [shared["id"]], {shared["id"]}
    yield "no applicable model", [zero, newer, off_model], "ref-C", 8, "optical prism zero", [], set()
    yield "no source yet at pinned date", [newer, shared], target, 1, "prism or bath calibration", [], set()
    retired = _doc("handling", target, 1, "Spindle oscillation damping for the liquid sample.")
    replacement = _doc("handling", target, 5, "Container label printing and archiving.")
    yield "retired text cannot win", [retired, replacement], target, 6, "spindle oscillation damping", [], set()
    yield "unrelated request", pool, target, 8, "ultrasonic thickness mapping of titanium", [], set()
    yield "unspecified task", pool, target, 8, "What should I do with this?", [], set()
    yield "empty request", pool, target, 8, " ", [], set()
    yield "duplicate source deduplicated", [shared, shared.copy()], target, 3, "bath equilibration", [shared["id"]], {shared["id"]}
    records = _catalog_records()
    yield ("actual catalog model and method", records, "agilent-1260-infinity-binary-lc", 1,
           "DIN 20481 caffeine in coffee", ["agilent-caffeine-in-coffee-din-20481@1"],
           {"agilent-caffeine-in-coffee-din-20481@1"})
    yield ("actual catalog shared method", records, "hanna-hi96800", 1,
           "fruit juice sampling for total soluble solids", ["oecd-fruit-soluble-solids@1"],
           {"oecd-fruit-soluble-solids@1", "hanna-hi96800-manual@1"})
    yield ("actual catalog manual retrieval", records, "hanna-hi96800", 1,
           "manufacturer manual for selecting refractive index scales and zeroing the prism",
           ["hanna-hi96800-manual@1"], {"hanna-hi96800-manual@1", "oecd-fruit-soluble-solids@1"})
    meter = _doc("solution", target, 2,
                 "Find salinity of a liquid using the meter response to dissolved sodium chloride.")
    yield ("paraphrased topic", [meter, paper], target, 4,
           "how salty is the sample?", [meter["id"]], {meter["id"]})
    docs = [_doc(f"optical-{n}", target, 1, "Optical prism alignment reference.") for n in range(5)]
    yield "result cap for equally useful sources", docs, target, 2, "optical prism alignment", None, {d["id"] for d in docs}


def grade(candidate):
    solve = getattr(candidate, "solve", candidate)
    report = []
    for name, documents, model, date, query, required_prefix, allowed in _cases():
        request = {"documents": deepcopy(documents), "model": model, "as_of": date, "query": query}
        try:
            actual = solve(request)
            shape = (isinstance(actual, list) and len(actual) <= 3
                     and all(isinstance(x, str) for x in actual)
                     and len(set(actual)) == len(actual))
            if required_prefix is None:
                correct = shape and bool(actual) and set(actual) <= allowed
            else:
                correct = shape and actual[:len(required_prefix)] == required_prefix and set(actual) <= allowed
            detail = f"returned {actual!r}; required prefix {required_prefix!r}; allowed {sorted(allowed)!r}"
            report.append((name, bool(correct), detail))
        except Exception as exc:
            report.append((name, False, f"{type(exc).__name__}: {exc}"))
    return report
