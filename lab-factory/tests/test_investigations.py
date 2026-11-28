from uuid import uuid4

import pytest

from labfactory import analysis_requests, briefing, investigations, tabular_service
from labfactory.context import ContextError
from labfactory.workorders import WorkOrderError


def request(project, objective, **choices):
    return dict(project_id=project, objective=objective, request_id=str(uuid4()), choices=choices)


def upload(store, project, name):
    return tabular_service.create_order(store, "Reviewer", {
        "project_id": project, "objective": "Estimate area", "unit": "units", "protocol_name": "method.md",
        "protocol": "Compare areas to standards.", "csv_name": name,
        "csv": "vial,kind,area,level\ns1,standard,10,1\ns2,standard,100,10\nc,control,50,\nu,unknown,75,\n",
        "mapping": {"id": "vial", "role": "kind", "signal": "area", "known": "level"},
        "control_expected": 5, "control_tolerance": 0.1})["id"]


def test_clarification_then_persistent_project_procedure(store):
    p = investigations.register(store, "Trace archive")
    assert investigations.register(store, "Trace archive") == p
    req = request(p["id"], "Reference alignment")
    assert investigations.resolve(store, "Reviewer", req)["field"] == "kind"
    assert investigations.inventory(store, p["id"])["resources"] == []
    req["choices"] = {"kind": "procedure"}
    result = investigations.resolve(store, "Reviewer", req)
    assert result == investigations.resolve(store, "Reviewer", req)
    draft, = result["resources"]
    assert draft["status"] == "needs_input"
    assert investigations.projects(store)["projects"][0]["id"] == p["id"]
    assert len(investigations.projects(store)["projects"]) == 1
    assert investigations.inventory(store, p["id"])["investigations"] == [result]
    with pytest.raises(WorkOrderError):
        investigations.resolve(store, "Reviewer", {**req, "objective": "different"})


def test_project_dataset_selection_ready_app_reuse_and_ambiguous_files(store):
    p, other = [investigations.register(store, name)["id"] for name in ("References", "Separate archive")]
    first = upload(store, p, "Tuesday-a.csv")
    second = upload(store, p, "Tuesday-b.csv")
    foreign = upload(store, other, "Tuesday-a.csv")
    req = request(p, "Analyze Tuesday readings")
    question = investigations.resolve(store, "Reviewer", req)
    assert question["field"] == "data"
    assert {o["id"] for o in question["options"]} == {first + "/uploads/readings", second + "/uploads/readings", "new"}
    with pytest.raises(WorkOrderError):
        investigations.resolve(store, "Reviewer", {**req, "choices": {"data": foreign + "/uploads/readings"}})
    missing = investigations.resolve(store, "Reviewer", request(p, "Analyze Friday.csv"))
    assert missing["field"] == "data" and "not found" in missing["question"]
    req = request(p, "Plot Tuesday-a.csv")
    result = investigations.resolve(store, "Reviewer", req)
    dataset, app = result["resources"]
    assert dataset["id"] == first + "/uploads/readings" and dataset["reused"]
    assert not app["reused"]
    ctx, = analysis_requests.detail(store, app["id"])["contexts"]
    assert ctx["dataset"]["digest"] == dataset["digest"] and ctx["dataset"]["columns"]["signal"] == "area"
    assert ctx["experiment"]["id"] == p
    analysis_requests.claim(store, app["id"], "Worker")
    assert analysis_requests.submit(store, app["id"], "Worker", {"turn": 1, "app": {
        "summary": "Area plot", "question": "", "html": "<html><body>Area</body></html>"}})["status"] == "ready"
    repeat = investigations.resolve(store, "Reviewer", request(p, "Plot Tuesday-a.csv"))
    assert repeat["resources"][1]["id"] == app["id"] and repeat["resources"][1]["reused"]
    assert len(analysis_requests.listing(store)) == 1
    combined = investigations.resolve(store, "Reviewer", request(p, "Plot Tuesday-a.csv and Tuesday-b.csv"))
    file_a, file_b, combined_app = combined["resources"]
    assert [file_a["id"], file_b["id"]] == [first + "/uploads/readings", second + "/uploads/readings"]
    assert not combined_app["reused"]
    pinned = analysis_requests.detail(store, combined_app["id"])["contexts"][0]["datasets"]
    assert [d["digest"] for d in pinned] == [file_a["digest"], file_b["digest"]]


def test_released_procedure_is_reused_and_pinned_to_app(store, uvvis_lab_dict, b12_experiment_dict):
    from labfactory.context import lab_from_dict, experiment_from_dict
    from labfactory.workorders import WorkOrders

    store.put_lab(lab_from_dict(uvvis_lab_dict))
    project = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(project)
    orders = WorkOrders(store)
    order = orders.create(project.id, "procedure", "Optical handling")
    orders.claim(order.id, "Author")
    orders.submit(order.id, "Author", {"steps": [{"text": "Record the reading.", "citations": ["sop-cuvette"]}]})
    orders.approve(order.id, "Reviewer", 1)
    procedure, = investigations.resolve(store, "Reviewer", request(project.id, "Optical handling"))["resources"]
    assert procedure["id"] == order.id and procedure["reused"]
    result = investigations.resolve(store, "Reviewer", request(project.id, "Analyze readings using Optical handling"))
    method, app = result["resources"]
    assert method["id"] == order.id and app["kind"] == "app"
    evidence = analysis_requests.detail(store, app["id"])["contexts"][0]["procedure"]
    assert evidence["order_id"] == order.id and evidence["submission"] == 1
    assert "Record the reading" in evidence["instructions"]


def test_legacy_stage_archive_can_be_attached_without_changing_its_snapshots(store):
    p, other = [investigations.register(store, title)["id"] for title in ("Stage archive", "Other stage")]
    key = analysis_requests.create(store, "Reviewer", {
        "request_id":str(uuid4()), "objective":"Plot stage drift", "project":"stage-example"})["id"]
    before = analysis_requests.detail(store, key)
    assert investigations.app_project(store, key) is None
    investigations.attach_app(store, p, key)
    investigations.attach_app(store, p, key)
    assert investigations.app_project(store, key) == p
    record, = investigations.inventory(store, p)["resources"]
    assert record["id"] == key
    assert investigations.inventory(store, other)["resources"] == []
    assert analysis_requests.detail(store, key) == before
    with pytest.raises(WorkOrderError):
        investigations.attach_app(store, other, key)


START = {"id": "readiness", "name": "Protocol readiness", "whenToUse": "Before a run.",
         "instructions": "List what is missing.", "stage": "start"}
RESULT = {"id": "calibration", "name": "Calibration review", "whenToUse": "On a result.",
          "instructions": "Check the range.", "stage": "result"}


def test_new_procedure_gets_start_skills_and_matched_sources(store):
    p = investigations.register(store, "Optics")
    req = {**request(p["id"], "Check wavelength accuracy on the Agilent Cary 60", kind="procedure"),
           "skills": [START, RESULT]}
    resource, = investigations.resolve(store, "Reviewer", req)["resources"]
    brief = resource["briefing"]
    assert brief["skills"] == [{"id": "readiness", "name": "Protocol readiness", "version": brief["skills"][0]["version"]}]
    assert len(brief["skills"][0]["version"]) == 64
    assert brief["instrument"].startswith("Agilent Technologies")
    assert "agilent-cary-60-user-guide" in [r["id"] for r in brief["references"]]
    assert briefing.load(store, resource["id"])["skills"][0]["instructions"] == "List what is missing."
    assert store.get_experiment("investigation-" + req["request_id"])[0].documents == ()


def test_new_app_gets_result_skills_in_its_pinned_context(store):
    p = investigations.register(store, "Honey")
    req = {**request(p["id"], "Analyze the honey moisture readings by refractometry", kind="app", data="new"),
           "skills": [START, RESULT]}
    resource, = investigations.resolve(store, "Reviewer", req)["resources"]
    assert analysis_requests.detail(store, resource["id"])["contexts"][0]["briefing"]["skills"][0]["id"] == "calibration"
    assert resource["briefing"]["skills"][0]["id"] == "calibration"


def test_reused_resources_carry_no_briefing(store):
    p = investigations.register(store, "References")["id"]
    upload(store, p, "Tuesday-a.csv")
    first = investigations.resolve(store, "Reviewer", request(p, "Plot Tuesday-a.csv"))
    app = first["resources"][1]
    analysis_requests.claim(store, app["id"], "Worker")
    analysis_requests.submit(store, app["id"], "Worker", {"turn": 1, "app": {
        "summary": "Area plot", "question": "", "html": "<html><body>Area</body></html>"}})
    repeat = investigations.resolve(store, "Reviewer", {**request(p, "Plot Tuesday-a.csv"), "skills": [RESULT]})
    assert all(r["reused"] for r in repeat["resources"])
    assert not any("briefing" in r for r in repeat["resources"])


def test_investigation_without_skills_or_matches_is_unchanged(store):
    p = investigations.register(store, "Plain")
    resource, = investigations.resolve(store, "Reviewer", request(p["id"], "zzqx vvkw", kind="procedure"))["resources"]
    assert "briefing" not in resource
    assert briefing.load(store, resource["id"]) is None


def test_invalid_skills_are_rejected_before_any_record_is_created(store):
    p = investigations.register(store, "Strict")
    cases = [request(p["id"], "zzqx vvkw", kind="procedure") | {"skills": bad}
             for bad in ([START] * 33, [{**START, "version": "0" * 64}], "calibration")]
    cases.append({**request(p["id"], "Reference alignment"), "skills": "calibration"})
    for req in cases:
        with pytest.raises(ContextError):
            investigations.resolve(store, "Reviewer", req)
    inventory = investigations.inventory(store, p["id"])
    assert inventory["investigations"] == [] and inventory["resources"] == []


def test_retry_with_same_skills_is_idempotent_and_changed_skills_conflict(store):
    p = investigations.register(store, "Retry")
    req = {**request(p["id"], "Check wavelength accuracy on the Agilent Cary 60", kind="procedure"), "skills": [START]}
    assert investigations.resolve(store, "Reviewer", req) == investigations.resolve(store, "Reviewer", req)
    with pytest.raises(WorkOrderError):
        investigations.resolve(store, "Reviewer", {**req, "skills": [RESULT]})


def _lab_project(store, instruments=True):
    from labfactory.context import Experiment, Instrument, Lab
    cary = Instrument("uv-1", "Bench spectrophotometer", "Agilent Cary 60", "1.0", (), ())
    store.put_lab(Lab("lab", "Lab", (cary,), ()))
    store.put_experiment(Experiment("proj", "lab", "Optics", "Optics", ("uv-1",), ()))
    return Lab, cary


def test_reuse_still_works_after_the_lab_drops_an_assigned_instrument(store):
    Lab, _ = _lab_project(store)
    ask = lambda: investigations.resolve(store, "R", request("proj", "Analyze the absorbance readings", kind="app"))
    app = ask()["resources"][-1]
    analysis_requests.claim(store, app["id"], "W")
    analysis_requests.submit(store, app["id"], "W", {"turn": 1, "app": {
        "summary": "s", "question": "", "html": "<html><body>x</body></html>"}})
    assert [r["reused"] for r in ask()["resources"]] == [True]
    store.put_lab(Lab("lab", "Lab", (), ()))
    assert [r["reused"] for r in ask()["resources"]] == [True]


def test_new_procedure_scopes_sources_to_the_project_instrument(store):
    _lab_project(store)
    result = investigations.resolve(store, "R", request("proj", "Check wavelength accuracy", kind="procedure"))
    assert result["resources"][-1]["briefing"]["instrument"] == "Agilent Technologies Cary 60"
