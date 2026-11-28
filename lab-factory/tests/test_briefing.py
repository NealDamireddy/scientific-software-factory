import json
import pytest

from labfactory import briefing, references
from labfactory.context import ContextError, Experiment, Instrument, Lab
from labfactory.workorders import WorkOrders


def skill(key, stage=None, text="Check the range."):
    return {"id": key, "name": key.title(), "whenToUse": "When it applies.", "instructions": text,
            **({"stage": stage} if stage else {})}


CARY = Instrument("uv-1", "Bench spectrophotometer", "Agilent Cary 60", "1.0", (), ())


def test_model_for_recognises_exactly_one_catalog_model():
    assert references.model_for("Verify wavelength on the Agilent Cary 60 before the run") == "agilent-cary-60"
    assert references.model_for("Measure absorbance at 550 nm") is None
    assert references.model_for("Compare the Agilent Cary 60 with the Agilent 7890B") is None


def test_pin_accepts_missing_skills_and_wraps_invalid_ones():
    assert briefing.pin(None) == []
    pinned = briefing.pin([skill("calibration", "result")])
    assert len(pinned[0]["version"]) == 64
    with pytest.raises(ContextError):
        briefing.pin([skill("a")] * 2)
    with pytest.raises(ContextError):
        briefing.pin([skill(str(n)) for n in range(33)])


def test_for_kind_filters_by_stage_and_keeps_unstaged_skills():
    pinned = briefing.pin([skill("plan", "start"), skill("cal", "result"), skill("rep", "repeat"), skill("any")])
    assert [s["id"] for s in briefing.for_kind("procedure", pinned)] == ["plan", "any"]
    assert [s["id"] for s in briefing.for_kind("app", pinned)] == ["cal", "rep", "any"]


def test_find_references_scopes_to_the_single_named_or_assigned_model():
    named = briefing.find_references("Check wavelength accuracy on the Agilent Cary 60", [])
    assigned = briefing.find_references("Check wavelength accuracy", [CARY])
    for found in (named, assigned):
        assert found["instrument"] == {"id": "agilent-cary-60", "manufacturer": "Agilent Technologies",
                                       "model": "Cary 60", "technique": "uv-vis"}
        assert 1 <= len(found["findings"]) <= briefing.MAX_REFERENCES
        assert "agilent-cary-60-user-guide" in [f["id"] for f in found["findings"]]
        assert set(found["findings"][0]) == {"id", "kind", "title", "publisher", "version", "url", "locator",
                                             "summary", "scope", "match", "reason", "digest"}
    assert set(named) == {"query", "catalog_digest", "instrument", "overview", "findings"}


def test_find_references_without_a_model_searches_all_instruments():
    found = briefing.find_references("Determine moisture in honey by refractometry", [])
    assert found["instrument"] is None and found["findings"]


def test_long_objective_is_truncated_not_rejected():
    found = briefing.find_references("Determine moisture in honey by refractometry " + "and record it " * 60, [])
    assert len(found["query"]) <= 300 and not found["query"].endswith(" ")


def test_no_match_or_library_error_gives_no_references(monkeypatch):
    assert briefing.find_references("zzqx vvkw", []) is None

    def broken(*_):
        raise ContextError("library unavailable")
    monkeypatch.setattr(references, "search", broken)
    assert briefing.find_references("Determine moisture in honey", []) is None


def test_build_summary_and_instructions():
    pinned = briefing.pin([skill("plan", "start"), skill("cal", "result")])
    assert briefing.build("procedure", [], "zzqx vvkw", []) is None
    assert briefing.instructions(None) == ""
    built = briefing.build("procedure", pinned, "Check wavelength accuracy on the Agilent Cary 60", [])
    assert [s["id"] for s in built["skills"]] == ["plan"]
    assert set(built) == {"skills", "reference_library"}
    assert briefing.instructions(built) == briefing.SKILLS_INSTRUCTION + " " + briefing.REFERENCES_INSTRUCTION
    only_skills = briefing.build("app", pinned, "zzqx vvkw", [])
    assert set(only_skills) == {"skills"} and briefing.instructions(only_skills) == briefing.SKILLS_INSTRUCTION
    digest = briefing.summary(built)
    assert digest["skills"] == [{"id": "plan", "name": "Plan", "version": pinned[0]["version"]}]
    assert digest["instrument"] == "Agilent Technologies Cary 60"
    assert set(digest["references"][0]) == {"id", "kind", "title", "url", "locator"}
    assert briefing.summary(only_skills) == {"skills": [{"id": "cal", "name": "Cal", "version": pinned[1]["version"]}],
                                             "references": [], "instrument": None}


def test_save_load_and_copy(store):
    store.put_lab(Lab("lab", "Lab", (), ()))
    store.put_experiment(Experiment("exp", "lab", "Title", "Goal", (), ()), allow_unassigned=True)
    orders = WorkOrders(store)
    first, second = (orders.create("exp", "procedure", "Goal", actor="Reviewer") for _ in range(2))
    value = briefing.build("app", briefing.pin([skill("cal", "result")]), "zzqx vvkw", [])
    assert briefing.load(store, first.id) is None
    briefing.save(store, first.id, None)
    assert briefing.load(store, first.id) is None
    briefing.save(store, first.id, value)
    assert briefing.load(store, first.id) == value
    briefing.copy(store, first.id, second.id)
    assert briefing.load(store, second.id) == value
    third = orders.create("exp", "procedure", "Goal", actor="Reviewer")
    briefing.copy(store, third.id, first.id)   # nothing to copy: the target keeps its own briefing
    assert briefing.load(store, first.id) == value


@pytest.mark.parametrize("name, error", [("model_for", ValueError), ("describe", KeyError)])
def test_any_library_failure_gives_no_references(monkeypatch, name, error):
    def fail(*args, **kwargs):
        raise error("broken")
    monkeypatch.setattr(references, name, fail)
    assert briefing.find_references("Determine moisture in honey by refractometry", []) is None


def test_mark_pinned_flags_findings_without_mutating():
    built = briefing.build("procedure", [], "Analyze the honey moisture readings by refractometry", [])
    first, second = [row["id"] for row in built["reference_library"]["findings"][:2]]
    before = json.dumps(built, sort_keys=True)
    marked = briefing.mark_pinned(built, {first: "library:" + first})
    assert json.dumps(built, sort_keys=True) == before
    findings = marked["reference_library"]["findings"]
    assert findings[0]["document_id"] == "library:" + first and "document_id" not in findings[1]
    refs = briefing.summary(marked)["references"]
    assert refs[0]["document_id"] == "library:" + first and "document_id" not in refs[1]
    assert briefing.mark_pinned(None, {first: "library:" + first}) is None
    only_skills = briefing.build("app", briefing.pin([skill("a")]), "zzqx vvkw", [])
    assert briefing.mark_pinned(only_skills, {first: "x"}) == only_skills


def test_reference_instruction_explains_pinned_findings():
    assert briefing.REFERENCES_INSTRUCTION == (
        "The reference_library entry lists reference-library sources matched to this objective. A finding "
        "with a document_id is pinned to this work order as that document: cite it like any other pinned "
        "document. Every other finding is a pointer, not evidence: never quote or cite it. When a needed "
        "method detail or instrument setting is missing from the pinned context, name the matching source "
        "and its locator in your question so the researcher can supply the passage.")
