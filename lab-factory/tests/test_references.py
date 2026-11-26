from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from labfactory import references
from labfactory.context import ContextError, canonical_digest


def test_collection_integrity():
    catalog = references.catalog()
    browse = references.search()
    assert browse["instrument"]["scope"] == "all" and browse["query"] == "" and not browse["brief"]
    rows = browse["findings"]
    assert len(rows) == len({row["url"] for row in rows}) == sum(catalog["counts"].values())
    models = {item["id"] for item in catalog["instruments"] if item["scope"] == "model"}
    assert models == {mid for row in rows if row["kind"] == "manual" for mid in row["instrument_ids"]}
    assert set(catalog["technique_names"]) >= {"ph", "conductivity", "ftir", "hplc", "gravimetry", "uv-vis"}
    for row in rows:
        raw = references.source(row["id"])
        assert raw.pop("digest") == canonical_digest(raw) == row["digest"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = list(pool.map(lambda ex: references.search(ex["instrument"], ex["q"]), catalog["examples"]))
    for result in parallel:
        ids = {r["id"] for r in result["findings"]}
        assert ids and all(set(b["source_ids"]) <= ids for b in result["brief"])
        assert result["catalog_digest"] == catalog["catalog_digest"]


@pytest.mark.parametrize(("scope", "q", "expected", "excluded"), [
    ("all", "What is the pH of water?", "usgs-nfm-ph", "california-swb-mp1"),
    ("other-uv-vis", "orthophosphate in drinking water", "epa-365-1-phosphorus", "who-phint6-cyanocobalamin"),
    ("other-gravimetry", "suspended solids in runoff", "epa-160-2-suspended-solids", "usgs-nfm-ph"),
    ("all", "Validate a volumetric flask using mass of distilled water", "nist-sop14-gravimetric-volume", "gray-2000-suspended-sediment"),
    ("agilent-cary-630", "identify polymers with FT-IR", "primpke-2018-ftir-polymers", "agilent-cary-60-user-guide"),
    ("thermo-orion-star-a215", "water conductance", "usgs-nfm-specific-conductance", "epa-365-1-phosphorus"),
    ("all", "find instructions for Agilent Cary 630", "agilent-cary-630-ftir-guide", "agilent-cary-60-user-guide"),
    ("all", "ME204 manual", "mettler-me-balance-operating-instructions", "agilent-cary-60-user-guide"),
    ("all", "A211 guide", "thermo-orion-star-a210-user-manual", "mettler-me-balance-operating-instructions"),
    ("all", "Measure vitamin B6 absorbance", "mahidol-2009-b-vitamin-tablets", "who-phint6-cyanocobalamin"),
])
def test_subject_and_instrument_match(scope, q, expected, excluded):
    results = references.search(scope, q)["findings"]
    ids = {r["id"] for r in results}
    assert expected in ids and excluded not in ids


def test_exact_hardware_and_independent_evidence():
    model = "agilent-1260-infinity-binary-lc"
    answer = references.search(model, "Measure caffeine in coffee")
    matches = {r["id"]: r for r in answer["findings"]}
    assert matches["agilent-caffeine-in-coffee-din-20481"]["match"] == "same_model_study"
    assert matches["agilent-1260-infinity-binary-system-guide"]["match"] == "instrument_manual"
    assert matches["albaqami-2023-coffee-caffeine"]["match"] == "related_method"
    assert "Shimadzu" in matches["albaqami-2023-coffee-caffeine"]["scope"]
    for scope in ("all", "other-hplc"):
        assert all(r["match"] not in ("instrument_manual", "same_model_study")
                   for r in references.search(scope, answer["query"])["findings"])
    assert references.search("all", "B₁₂")["findings"] == references.search("all", "vitamin B-12")["findings"]


@pytest.mark.parametrize("q", ["determine zinc in drinking water", "measure dissolved copper in tap water",
                               "measure codeine in tablets", "quantify kryptonite using colorimetry",
                               "find operating instructions for Agilent Cary 650", "Measure vitamin C absorbance",
                               "record visible spectrum of methylene blue"])
def test_unsupported_subject_does_not_borrow_matrix_or_instrument_evidence(q):
    result = references.search("all", q)
    assert result["findings"] == [] and not result["brief"]


def test_unknown_and_malformed_inputs():
    for args in [("missing", "water"), ("all", "a" * 301), ("all", None), ([], ""), ("all", "\ud800")]:
        with pytest.raises(ContextError):
            references.search(*args)
    with pytest.raises(ContextError):
        references.source("missing")


def test_concurrent_readers_get_the_same_ranked_records_as_serial_search():
    examples = [(ex["instrument"], ex["q"]) for ex in references.catalog()["examples"]]
    cases = examples + [("all", q) for _, q in examples] + [("all", "ME204 manual"), ("all", "B₁₂")]

    def ranked(case):
        return [r["id"] for r in references.search(*case)["findings"]]

    expected = {case: ranked(case) for case in cases}
    with ThreadPoolExecutor(max_workers=20) as pool:
        tasks = cases * 12
        assert list(pool.map(ranked, tasks)) == [expected[case] for case in tasks]


def test_new_techniques_and_sources_are_searchable_from_data_alone(tmp_path, monkeypatch):
    def put(name, value):
        (tmp_path / name).write_text(json.dumps(value))
    put("search.json", {"aliases": {}, "examples": [], "technique_names": {}, "context_terms": ["water"]})
    put("instruments-new.json", [{"id": "test-prism", "manufacturer": "Test", "model": "Prism",
                                  "aliases": [], "technique": "refractometry"}])
    record = {**references.source("usgs-nfm-ph"), "id": "test-refractometry", "kind": "paper",
              "title": "Sucrose refractometry", "topics": ["sucrose"], "techniques": ["refractometry"]}
    del record["digest"]
    put("new-methods.json", [record])
    index = references.ReferenceIndex(tmp_path)
    monkeypatch.setattr(references, "_index", lambda: index)
    found = references.search("other-refractometry", "measure sucrose in water")
    assert [r["id"] for r in found["findings"]] == ["test-refractometry"]


def test_every_catalog_model_has_two_sourced_experiments():
    catalog = references.catalog()
    assert len({g["q"].casefold() for g in catalog["experiments"]}) == len(catalog["experiments"])
    models = [item for item in catalog["instruments"] if item["scope"] == "model"]
    for model in models:
        guides = [g for g in catalog["experiments"] if set(g["techniques"]).intersection(model["techniques"])]
        assert len({g["q"] for g in guides}) >= 2, model["id"]
        for guide in guides:
            result = references.search(model["id"], guide["q"])
            cited_ids = {key for section in result["brief"] for key in section["source_ids"]}
            cited = {row["kind"]: row for row in result["findings"] if row["id"] in cited_ids}
            assert cited["manual"]["match"] == "instrument_manual"
            assert model["id"] in cited["manual"]["instrument_ids"]
            for kind in ("procedure", "paper"):
                assert cited[kind]["id"] in guide[kind], (guide["q"], model["id"])
            assert result["requirements"] == guide["requirements"] and result["requirements"].strip()


def test_incompatible_optics_materials_and_pipette_ranges():
    tungsten = "epa-180-1-nephelometry"
    for model, present in (("hach-2100q", True), ("hach-2100qis", False)):
        assert (tungsten in {s["id"] for s in references.search(model, "drinking water turbidity")["findings"]}) is present
    oven = references.search("memmert-uf55", "Measure flour moisture")
    assert oven["findings"] == [] and "flour" in oven["incompatible_terms"]
    assert "usda-ars-flour-moisture" in {s["id"] for s in references.search("mettler-toledo-me204", "flour moisture")["findings"]}
    query = "Check dye serial dilution precision"
    for model, applicable, excluded in (
        ("eppendorf-research-plus-200", "clark-2023-microplate-serial-dilutions", "delaware-dye-tube-dilution"),
        ("eppendorf-research-plus-1000", "delaware-dye-tube-dilution", "clark-2023-microplate-serial-dilutions"),
    ):
        hits = {r["id"] for r in references.search(model, query)["findings"]}
        assert applicable in hits and excluded not in hits


def test_a_companion_technique_can_be_part_of_an_instrument_question():
    result = references.search("eppendorf-research-plus-200", "Check gravimetric pipette delivery repeatability")
    findings = {row["id"] for row in result["findings"]}
    assert {"eppendorf-research-plus-operating-manual", "npl-2004-piston-pipette-calibration",
            "ouyang-2008-pipette-dye-volume"} <= findings
    assert result["requirements"] == ""


def test_manufacturer_procedure_and_measured_model_have_distinct_labels():
    result = references.search("hanna-hi96800", "Measure honey moisture")
    matches = {r["id"]: r["match"] for r in result["findings"]}
    assert matches["hanna-hi96800-manual"] == "instrument_manual"
    assert matches["hanna-honey-refractive-index"] == "model_method"
    assert matches["barbour-2026-honey-moisture"] == "same_model_study"
