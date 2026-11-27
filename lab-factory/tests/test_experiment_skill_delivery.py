import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from lab_codex_worker import experiment_review
from lab_codex_worker.skills import pin_skills
from labfactory import tabular_worker


def request():
    return {
        "deliveryId": "97ad6e2b-b90d-4f8f-ada2-3cd921b27c79",
        "briefing": {"objective": "Measure absorbance", "project": "Illustrative study", "mode": "original",
                     "method": {"name": "UV–Vis", "revision": "1.2", "wavelengthNm": 361}},
        "skills": [{"id": "audit", "name": "Audit", "whenToUse": "Before release",
                    "instructions": "Check the μL units.\nCite the record.", "stage": "result"}],
    }


def ack(prompt, schema, **kwargs):
    envelope = json.loads(prompt.splitlines()[-1])
    return SimpleNamespace(answer={"acknowledgement": envelope["acknowledgement"], "review": "Request the method log."})


def test_delivered_content_and_idempotent_receipt(monkeypatch, tmp_path):
    payload = request()
    payload["skills"][0]["endpoint"] = "excluded-private-url"
    payload["briefing"]["credentials"] = "excluded-private-token"
    skill = payload["skills"][0]
    prompts = []

    def invoke(prompt, schema, **kwargs):
        prompts.append(prompt)
        return ack(prompt, schema, **kwargs)

    monkeypatch.setattr(experiment_review, "run_worker", invoke)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, duplicate = pool.map(lambda _: experiment_review.review_delivery(payload, tmp_path), range(2))
    assert first == duplicate and len(prompts) == 1 and first["receivedAt"]
    assert "excluded-private" not in prompts[0]
    sent = json.loads(prompts[0].splitlines()[-1])["enabledSkills"][0]
    assert {key: sent[key] for key in ("name", "whenToUse", "instructions", "stage")} == {
        key: skill[key] for key in ("name", "whenToUse", "instructions", "stage")}
    version = hashlib.sha256('["audit","Audit","Before release","Check the μL units.\\nCite the record.","result"]'.encode()).hexdigest()
    assert first["skills"] == [{"id": "audit", "name": "Audit", "version": version}]
    assert version == sent["version"]
    skill["instructions"] += " Check the lot."
    with pytest.raises(experiment_review.DeliveryConflict):
        experiment_review.review_delivery(payload, tmp_path)
    assert len(prompts) == 1
    payload["deliveryId"] = "ab2132ea-62a3-4b8b-aa5b-b529dc3ca1bc"
    second = experiment_review.review_delivery(payload, tmp_path)
    assert second["skills"][0]["version"] != version


def test_failed_ack_has_no_receipt_and_can_retry(monkeypatch, tmp_path):
    payload = request()
    payload["skills"] = []
    monkeypatch.setattr(experiment_review, "run_worker", lambda *_args, **_kwargs:
                        SimpleNamespace(answer={"acknowledgement": "wrong", "review": "Example"}))
    with pytest.raises(RuntimeError, match="acknowledge"):
        experiment_review.review_delivery(payload, tmp_path)
    row = json.loads((tmp_path / (payload["deliveryId"] + ".json")).read_text())
    assert "receipt" not in row
    monkeypatch.setattr(experiment_review, "run_worker", ack)
    assert experiment_review.review_delivery(payload, tmp_path)["skills"] == []


def test_author_receives_pinned_skill_once(monkeypatch):
    skills = pin_skills(request()["skills"])
    context = {"instructions": "host", "analysis": {"protocol": "measure", "skills": skills}}
    before = deepcopy(context)
    prompts = []
    def invoke(prompt, *_args, **_kwargs):
        prompts.append(json.loads(prompt.splitlines()[-1]))
        return SimpleNamespace(answer={"question": "Which unit is required?"})
    monkeypatch.setattr(tabular_worker, "run_worker", invoke)
    tabular_worker.generate(context)
    assert prompts == [{"experiment": {"protocol": "measure"}, "instructions": "host", "enabledSkills": skills}]
    assert context == before
    context["analysis"]["skills"][0]["instructions"] += "X"
    with pytest.raises(ValueError, match="version"):
        tabular_worker.generate(context)
    assert len(prompts) == 1


def test_input_validation():
    skill = request()["skills"][0]
    for bad in (None, [skill, skill], [{**skill, "stage": "unknown"}], [{**skill, "instructions": " "}],
                [{**skill, "instructions": "X" * 32769}]):
        with pytest.raises(ValueError):
            pin_skills(bad)
