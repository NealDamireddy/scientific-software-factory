import hashlib
from html import unescape
from uuid import uuid4

import pytest

from labfactory import analysis_requests, offline_app
from labfactory.agent import AgentTools
from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.workorders import WorkOrderError


def test_offline_app_reuses_context_and_turns(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    store.put_experiment(experiment_from_dict(b12_experiment_dict))
    project = {"experiment_id": b12_experiment_dict["id"]}
    key = analysis_requests.create(store, "reviewer", {"request_id": str(uuid4()), "project": project,
                                   "objective": "Build an offline analysis app."}, analysis_requests.APP_PREFIX)["id"]
    agent = AgentTools(store)
    assert analysis_requests.listing(store, prefix=analysis_requests.PLOT_PREFIX) == []
    assert agent.list_work_orders()[0]["kind"] == "offline_app"
    ctx = agent.get_work_order_context(key)["offline_app"]["contexts"][0]
    assert ctx["experiment"]["revision"] == 1 and ctx["experiment"]["documents"]
    question = {"app": {"question": "Which alignment?", "summary": "Read the manual.", "html": ""}, "turn": 1}
    first = agent.claim_work_order(key, "author")["claim_id"]
    assert "error" in agent.submit_artifact(key, "author", question)
    assert agent.submit_artifact(key, "author", question, first)["status"] == "needs_input"
    with pytest.raises(WorkOrderError):
        analysis_requests.download(store, key)
    analysis_requests.answer(store, key, "reviewer", {"turn": 1, "answer": "Use the reference."})
    following = agent.get_work_order_context(key)["offline_app"]
    assert following["history"][0]["answer"] == "Use the reference."
    assert following["contexts"][0] == ctx
    second = agent.claim_work_order(key, "author")["claim_id"]
    source = '<!doctype html><html><body><h1>Custom output</h1></body></html>'
    candidate = {"turn": 2, "app": {"question": "", "summary": "Confirmed method.", "html": source}}
    assert "error" in agent.submit_artifact(key, "author", candidate, first)
    assert agent.submit_artifact(key, "author", candidate, second)["status"] == "ready"
    html = analysis_requests.download(store, key)
    assert "form-action 'none'" in html
    assert source in unescape(html)
    assert 'sandbox="allow-scripts allow-downloads allow-forms"' in html
    assert analysis_requests.detail(store, key)["artifact_digest"] == hashlib.sha256(html.encode()).hexdigest()


@pytest.mark.parametrize("question,html", [("Why?", "<html></html>"), ("", ""), ("", "a recipe"), ("", "<html>" + "a"*120000)])
def test_invalid_app_does_not_replace_a_question(question, html):
    with pytest.raises(ValueError):
        offline_app.validate({"summary": "Method", "question": question, "html": html})
