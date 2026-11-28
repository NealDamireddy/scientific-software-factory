import json
from pathlib import Path

import pytest

from labfactory import briefing, first_draft, investigations, procedure_drafts, source_drafter, tabular_service
from labfactory.agent import AgentTools
from labfactory.procedure_drafts import passages

FIXTURE = Path(__file__).parent / "fixtures" / "procedure_drafts" / "filters.json"
SKILL = {"id": "readiness", "name": "Protocol readiness", "whenToUse": "Before a run.",
         "instructions": "List what is missing before starting.", "stage": "start"}
BRIEF = briefing.build("procedure", briefing.pin([SKILL]),
                       "Check wavelength accuracy on the Agilent Cary 60", [])


def _start(store):
    data = json.loads(FIXTURE.read_text())
    return first_draft.start(store, "Reviewer", data)["order"]["id"]


def _flow(store, monkeypatch, saved):
    order_id = _start(store)
    if saved:
        briefing.save(store, order_id, BRIEF)
    seen = {}

    def prepare(lab, exp, context, timeout):
        seen["prepare"] = dict(context)
        refs = [{"document": p["document"], "passage": p["passage"], "quote": p["text"]}
                for p in passages(lab, exp)]
        return [{"index": 1, "search": "study design", "finding": "Use the supplied study design.",
                 "status": "resolved", "question": "", "goal_quote": "", "hits": [], "evidence": refs}]

    def review(context, *_):
        seen["review"] = dict(context)
        return [{"index": 1, "steps": [1], "passed": True, "reason": "Implements the study decision."}]

    def generate(context, feedback):
        seen["generate"] = dict(context)
        selected = context["passages"]
        return {"steps": [{
            "text": "Measure each identified filter.",
            "citations": list(dict.fromkeys(p["document"] for p in selected)),
            "evidence": [{"document": p["document"], "passage": p["passage"], "quote": p["text"]}
                         for p in selected],
            "action": {"instrument_id": "photometer-1", "command": "read_transmittance",
                       "settings": [{"parameter": "wavelength", "value": 520, "unit": "nm"}]}}]}

    monkeypatch.setattr(source_drafter.decision_evidence, "prepare", prepare)
    monkeypatch.setattr(source_drafter.decision_evidence, "review", review)
    monkeypatch.setattr(source_drafter, "generate", generate)
    pending = first_draft.detail(store, order_id)
    source_drafter.complete(lambda op, write=False: op(store), pending)
    return seen


def test_author_prompt_carries_the_briefing_instructions(monkeypatch):
    prompts = []

    class Result:
        answer = {"question": "", "question_kind": "", "steps": []}

    monkeypatch.setattr(source_drafter, "run_worker", lambda prompt, *a, **k: prompts.append(prompt) or Result())
    source_drafter.generate({"goal": "g", "briefing": BRIEF})
    prompt = prompts[-1]
    assert briefing.instructions(BRIEF) in prompt
    assert "List what is missing before starting." in prompt
    assert prompt.startswith(source_drafter._PROMPT)
    source_drafter.generate({"goal": "g"})
    assert prompts[-1] == source_drafter._PROMPT + "\n" + json.dumps(
        {"context": {"goal": "g"}, "checker_feedback": None}, ensure_ascii=False)


def test_briefing_reaches_the_author_only(store, monkeypatch):
    seen = _flow(store, monkeypatch, True)
    assert seen["generate"]["briefing"] == BRIEF
    assert "briefing" not in seen["prepare"]
    assert "briefing" not in seen["review"]


def test_order_without_a_briefing_is_unchanged(store, monkeypatch):
    seen = _flow(store, monkeypatch, False)
    assert "briefing" not in seen["generate"]


def test_follow_up_order_keeps_the_briefing(store):
    _start(store)
    first = procedure_drafts.create(store, "glass-filters", "Reviewer")
    briefing.save(store, first.id, BRIEF)
    second = procedure_drafts.create(store, "glass-filters", "Reviewer", previous=first.id)
    assert briefing.load(store, second.id) == BRIEF


def test_mcp_context_includes_the_briefing_and_its_instructions(store):
    _start(store)
    order = procedure_drafts.create(store, "glass-filters", "Reviewer")
    plain = procedure_drafts.create(store, "glass-filters", "Reviewer")
    briefing.save(store, order.id, BRIEF)
    context = AgentTools(store).get_work_order_context(order.id)
    assert context["briefing"] == BRIEF
    assert context["instructions"].endswith(briefing.instructions(BRIEF))
    context = AgentTools(store).get_work_order_context(plain.id)
    assert "briefing" not in context
    assert briefing.SKILLS_INSTRUCTION not in context["instructions"]


def test_mcp_tabular_context_tells_the_agent_to_apply_supplied_skills(store):
    project = investigations.register(store, "Trace archive")["id"]
    payload = {
        "project_id": project, "objective": "Estimate area", "unit": "units", "protocol_name": "method.md",
        "protocol": "Compare areas to standards.", "csv_name": "a.csv",
        "csv": "vial,kind,area,level\ns1,standard,10,1\ns2,standard,100,10\nc,control,50,\nu,unknown,75,\n",
        "mapping": {"id": "vial", "role": "kind", "signal": "area", "known": "level"},
        "control_expected": 5, "control_tolerance": 0.1}
    with_skills = tabular_service.create_order(store, "Reviewer", {**payload, "skills": [SKILL]})["id"]
    without = tabular_service.create_order(store, "Reviewer", {**payload, "csv_name": "b.csv"})["id"]
    tools = AgentTools(store)
    assert tools.get_work_order_context(with_skills)["instructions"].endswith(briefing.SKILLS_INSTRUCTION)
    assert briefing.SKILLS_INSTRUCTION not in tools.get_work_order_context(without)["instructions"]
