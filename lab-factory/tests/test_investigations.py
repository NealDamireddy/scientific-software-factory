from dataclasses import replace
from uuid import uuid4

import pytest

from labfactory import analysis_requests, briefing, investigations, research_experiments, tabular_service
from labfactory.context import ContextError, Document
from labfactory.store import NotFound, Store
from labfactory.workorders import WorkOrderError


def request(project, objective, **choices):
    return dict(project_id=project, objective=objective, request_id=str(uuid4()), choices=choices)


def upload(store, project, name, **scope):
    return tabular_service.create_order(store, "Reviewer", {
        "project_id": project, "objective": "Estimate area", "unit": "units", "protocol_name": "method.md",
        "protocol": "Compare areas to standards.", "csv_name": name,
        "csv": "vial,kind,area,level\ns1,standard,10,1\ns2,standard,100,10\nc,control,50,\nu,unknown,75,\n",
        "mapping": {"id": "vial", "role": "kind", "signal": "area", "known": "level"},
        "control_expected": 5, "control_tolerance": 0.1, **scope})["id"]


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


def test_app_reuse_requires_matching_analysis_on_the_same_file(store):
    project = investigations.register(store, "Weekly readings")["id"]
    upload(store, project, "Tuesday.csv")
    objective = "Calculate the mean of Tuesday.csv"
    _, mean = investigations.resolve(store, "Reviewer", request(project, objective))["resources"]
    analysis_requests.claim(store, mean["id"], "Worker")
    analysis_requests.submit(store, mean["id"], "Worker", {"turn": 1, "app": {
        "summary": "Mean calculation", "question": "", "html": "<html><body>Mean</body></html>"}})

    _, repeat = investigations.resolve(store, "Reviewer", request(project, objective))["resources"]
    assert repeat["id"] == mean["id"] and repeat["reused"]
    _, plot = investigations.resolve(store, "Reviewer", request(project, "Plot Tuesday.csv"))["resources"]
    assert plot["id"] != mean["id"] and not plot["reused"]
    upload(store, project, "Wednesday.csv", csv=(
        "vial,kind,area,level\ns1,standard,10,1\ns2,standard,100,10\nc,control,50,\nu,unknown,77,\n"))
    different = investigations.resolve(store, "Reviewer", request(project, "Calculate the mean of Wednesday.csv"))
    assert different["field"] == "app"
    # Partial operation matches need a decision even when only one app is ready.
    question = investigations.resolve(store, "Reviewer", request(project, "Calculate the median of Tuesday.csv"))
    assert question["field"] == "app"
    assert {option["id"] for option in question["options"]} == {mean["id"], "new"}


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


def test_experiment_metadata_history_and_project_scoped_resources(store):
    first_project = investigations.register(store, "Archive", hypothesis="Measurements agree.")
    project = first_project["id"]
    other_project = investigations.register(store, "Separate archive")["id"]
    assert len(investigations.projects(store)["labs"]) == 1
    research_experiments.set_hypothesis(store, project, "Measurements agree across sessions.")
    scientific = {**request(project, "Do the archive groups agree?"), "start_experiment": True}
    recorded = investigations.resolve(store, "Reviewer", scientific)
    assert recorded["recorded"] and investigations.resolve(store, "Reviewer", scientific) == recorded
    experiment = recorded["experiment_id"]
    create_sibling = {"project_id": project, "request_id": str(uuid4()), "title": "Repeat", "question": "Does it repeat?"}
    sibling = research_experiments.create(store, "Reviewer", create_sibling)
    assert research_experiments.create(store, "Reviewer", create_sibling) == sibling
    initial, = [r for r in investigations.inventory(store, project)["experiments"] if r["id"] == experiment]
    assert initial["finding"] == "" and initial["requests"] == initial["resources"] == []
    edits = dict(project_id=project, title="Reference agreement", question="Are the references consistent?",
                 finding="Two readings differed.")
    assert research_experiments.update(store, experiment, edits)["title"] == edits["title"]
    req = {**request(project, "Build a new reference summary app"), "experiment_id": experiment}
    result = investigations.resolve(store, "Reviewer", req)
    procedure = investigations.resolve(store, "Reviewer", {
        **request(project, "Draft a new procedure for reviewing an archived balance entry"), "experiment_id": experiment})
    app_id, procedure_id = result["resources"][0]["id"], procedure["resources"][0]["id"]
    assert result["id"] != result["experiment_id"] == experiment
    assert investigations.resolve(store, "Reviewer", req) == result
    research_experiments.update(store, sibling["id"], {"project_id": project, "attach_resource_id": app_id})
    with pytest.raises(NotFound):
        investigations.resolve(store, "Reviewer", {**request(other_project, "Build an app"), "experiment_id": experiment})
    with pytest.raises(NotFound):
        research_experiments.update(store, sibling["id"], {"project_id": other_project, "attach_resource_id": app_id})
    foreign = upload(store, other_project, "foreign.csv")
    with pytest.raises(NotFound):
        research_experiments.update(store, experiment, {"project_id": project, "attach_resource_id": foreign})
    with pytest.raises(ContextError):
        research_experiments.update(store, experiment, {"project_id": project, "title": ""})
    inv = investigations.inventory(store, project)
    assert inv["hypothesis"] == "Measurements agree across sessions."
    assert inv["investigations"] == [procedure, result]
    record = next(e for e in inv["experiments"] if e["id"] == experiment)
    assert record["question"] == edits["question"] and record["finding"] == edits["finding"]
    assert record["requests"] == inv["investigations"]
    assert {r["id"] for r in record["resources"]} == {app_id, procedure_id}
    other = next(e for e in inv["experiments"] if e["id"] == sibling["id"])
    assert [r["id"] for r in other["resources"]] == [app_id] and other["requests"] == []


def test_scoped_upload_attaches_app_and_data_atomically(store):
    project = investigations.register(store, "Review archive")["id"]
    other = investigations.register(store, "Review two")["id"]
    experiment = research_experiments.create(store, "Reviewer", dict(
        project_id=project, request_id=str(uuid4()), question="Which records differ?"))["id"]
    with pytest.raises(NotFound):
        upload(store, other, "wrong-site.csv", research_experiment_id=experiment)
    assert investigations.inventory(store, other)["resources"] == []
    key = upload(store, project, "readings.csv", research_experiment_id=experiment)
    independent = upload(store, project, "project-only.csv")
    inv = investigations.inventory(store, project)
    assert independent in [r["id"] for r in inv["resources"]]
    assert {r["id"] for r in inv["experiments"][0]["resources"]} == {key, key + "/uploads/readings"}
    from labfactory.workorders import WorkOrders
    assert tabular_service.reviewer_context(store, WorkOrders(store).get(key))["research_experiment_id"] == experiment


def test_upgrading_legacy_requests_preserves_ids_snapshots_and_retry(tmp_path):
    import json

    dbfile = tmp_path / "legacy.sqlite3"
    with Store(dbfile) as store:
        project = investigations.register(store, "Legacy archive")["id"]
        objective = "Have the worker draft a new procedure for reviewing an archived balance entry. Use saved readings."
        req = request(project, objective)
        current = investigations.resolve(store, "Reviewer", req)
        assert research_experiments.short_title("Build a new mass summary app for Tuesday.csv. Group every row.") == "Mass summary app for Tuesday.csv"
        order = current["resources"][0]["id"]
        old = {k:v for k,v in current.items() if k != "experiment_id"}
        db = store.connection
        db.execute("UPDATE research_investigations SET result=? WHERE id=?", (json.dumps(old), current["id"]))
        for name in ("research_experiment_resources", "research_experiment_requests", "research_experiments", "research_project_info"):
            db.execute(f"DROP TABLE {name}")
    for _ in range(2):
        with Store(dbfile) as store:
            inv = investigations.inventory(store, project)
            experiment, = inv["experiments"]
            assert experiment["id"] == current["id"]
            assert experiment["title"] == "Reviewing an archived balance entry"
            assert experiment["question"] == objective and experiment["finding"] == ""
            assert experiment["requests"] == inv["investigations"] == [current]
            assert [r["id"] for r in experiment["resources"]] == [order]
            assert json.loads(store.connection.execute("SELECT result FROM research_investigations").fetchone()[0]) == old
            assert investigations.resolve(store, "Reviewer", req) == current
            assert store.connection.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 1


def test_followup_prefers_attached_readings_and_honors_named_project_files(store):
    project = investigations.register(store, "Mass reading archive")["id"]
    experiment = research_experiments.create(store, "Reviewer", {
        "project_id": project, "request_id": str(uuid4()), "question": "How stable are the readings?"})["id"]
    first = upload(store, project, "first.csv", research_experiment_id=experiment)
    # The project file list coalesces identical uploads, but the experiment
    # retains its original input and its provenance.
    duplicate = upload(store, project, "first.csv")
    other = upload(store, project, "sibling.csv")
    def followup(objective, **choices):
        return investigations.resolve(store, "Reviewer", {**request(project, objective, **choices), "experiment_id": experiment})
    result = followup("Summarize these readings", app="new")
    data, app = result["resources"]
    assert data["id"] == first + "/uploads/readings" and data["reused"]
    assert data["id"] != duplicate + "/uploads/readings"
    assert analysis_requests.detail(store, app["id"])["contexts"][0]["dataset"]["id"] == data["id"]
    same = followup("Plot this dataset against first.csv", app="new")
    assert [r["id"] for r in same["resources"] if r["kind"] == "data"] == [data["id"]]
    named = followup("Plot this dataset against sibling.csv", app="new")
    comparison = [data["id"], other + "/uploads/readings"]
    assert [r["id"] for r in named["resources"] if r["kind"] == "data"] == comparison
    ctx, = analysis_requests.detail(store, named["resources"][-1]["id"])["contexts"]
    assert [r["id"] for r in ctx["datasets"]] == comparison
    clarified = followup("Summarize this dataset", app="new")
    assert clarified["field"] == "data"
    assert {o["id"] for o in clarified["options"]} == {data["id"], other + "/uploads/readings", "new"}
    target = upload(store, project, "target.csv") + "/uploads/readings"
    ambiguous = {**request(project, "Plot this dataset against target.csv", app="new"), "experiment_id": experiment}
    question = investigations.resolve(store, "Reviewer", ambiguous)
    assert question["field"] == "data" and {o["id"] for o in question["options"]} == {*comparison, "new"}
    ambiguous["choices"]["data"] = other + "/uploads/readings"
    resolved = investigations.resolve(store, "Reviewer", ambiguous)
    assert [r["id"] for r in resolved["resources"] if r["kind"] == "data"] == [other + "/uploads/readings", target]
    inv = investigations.inventory(store, project)
    assert data["id"] in {r["id"] for r in inv["experiments"][0]["resources"]}


def test_comparison_with_two_ambiguous_references_preserves_each_answer(store):
    project = investigations.register(store, "Comparison inputs")["id"]
    experiment = research_experiments.create(store, "Reviewer", {
        "project_id": project, "request_id": str(uuid4()), "question": "Which files agree?"})["id"]
    attached = [upload(store, project, name, research_experiment_id=experiment) + "/uploads/readings"
                for name in ("first.csv", "second.csv")]
    baseline = upload(store, project, "baseline.csv") + "/uploads/readings"
    other = upload(store, project, "baseline.csv", csv=(
        "vial,kind,area,level\ns1,standard,10,1\ns2,standard,100,10\nc,control,50,\nu,unknown,76,\n")) + "/uploads/readings"
    req = {**request(project, "Plot this dataset against baseline.csv"), "experiment_id": experiment}
    question = investigations.resolve(store, "Reviewer", req)
    assert {o["id"] for o in question["options"]} == {*attached, "new"}
    req["choices"][question["field"]] = attached[0]
    question = investigations.resolve(store, "Reviewer", req)
    assert {o["id"] for o in question["options"]} == {baseline, other, "new"}
    req["choices"][question["field"]] = attached[0]
    with pytest.raises(WorkOrderError):
        investigations.resolve(store, "Reviewer", req)
    req["choices"][question["field"]] = baseline
    resolved = investigations.resolve(store, "Reviewer", req)
    assert [r["id"] for r in resolved["resources"] if r["kind"] == "data"] == [attached[0], baseline]


def test_no_attached_dataset_retains_project_default_and_rejects_stale_answers(store):
    project = investigations.register(store, "Project inputs")["id"]
    experiment = research_experiments.create(store, "Reviewer", {
        "project_id": project, "request_id": str(uuid4()), "question": "Which input?"})["id"]
    first = upload(store, project, "first.csv") + "/uploads/readings"
    result = investigations.resolve(store, "Reviewer", {
        **request(project, "Analyze this dataset"), "experiment_id": experiment})
    assert result["resources"][0]["id"] == first
    second = upload(store, project, "second.csv") + "/uploads/readings"
    req = {**request(project, "Plot this dataset against second.csv"), "experiment_id": experiment}
    for stale in ({"data": "missing"}, {"data:2": second}):
        with pytest.raises(WorkOrderError):
            investigations.resolve(store, "Reviewer", {**req, "choices": stale})


def test_attached_procedure_survives_a_revision(store):
    from labfactory import procedure_drafts
    from labfactory.workorders import WorkOrders

    project = investigations.register(store, "Revision archive")["id"]
    experiment = research_experiments.create(store, "Reviewer", {
        "project_id": project, "request_id": str(uuid4()), "question": "Do the results align?"})["id"]
    first = procedure_drafts.create(store, project, "Reviewer")
    research_experiments.update(store, experiment, {"project_id": project, "attach_resource_id": first.id})
    orders = WorkOrders(store)
    orders.claim(first.id, "Worker")
    def attached_status():
        procedure, = investigations.inventory(store, project)["experiments"][0]["resources"]
        return procedure["status"]

    assert attached_status() == "in_progress"
    orders.submit(first.id, "Worker", {"needs_input": "Which record should be checked?"})
    assert attached_status() == "needs_input"
    revision = procedure_drafts.add_source(store, first.id, "Reviewer", "Worksheet", "Check the archived entries.")
    view = investigations.inventory(store, project)
    assert [r["id"] for r in view["resources"]] == [revision]
    original, = view["experiments"][0]["resources"]
    assert original["id"] == first.id and original["next_order"] == revision
    assert original["status"] == "superseded"


def test_same_project_title_in_two_labs_keeps_legacy_identity(store):
    from labfactory.context import Experiment, Lab, canonical_digest
    title = "Density study"
    legacy = "workspace-" + canonical_digest(title)
    legacy_lab = "lab-" + legacy
    store.put_lab(Lab(legacy_lab, "Balance lab", (), ()))
    store.put_experiment(Experiment(legacy, legacy_lab, title, title, (), ()), allow_unassigned=True)
    assert investigations.register(store, title)["id"] == legacy
    assert investigations.register(store, title, legacy_lab)["id"] == legacy
    fresh = investigations.register(store, title, "research-workspace", "Density varies by group.")
    assert fresh["id"] != legacy and fresh["lab_id"] == "research-workspace"
    assert investigations.register(store, title, "research-workspace") == fresh
    assert investigations.inventory(store, legacy)["hypothesis"] == ""


def test_added_work_in_an_experiment_carries_the_briefing_and_reuse_does_not(store):
    project = investigations.register(store, "Experiments")["id"]
    experiment = research_experiments.create(store, "Reviewer", {
        "project_id": project, "request_id": str(uuid4()), "question": "Does the wavelength hold?"})["id"]
    req = {**request(project, "Check wavelength accuracy on the Agilent Cary 60", kind="procedure"),
           "experiment_id": experiment, "skills": [START]}
    result = investigations.resolve(store, "Reviewer", req)
    resource, = result["resources"]
    assert result["experiment_id"] == experiment and resource["briefing"]["skills"][0]["id"] == "readiness"
    assert briefing.load(store, resource["id"])["skills"][0]["id"] == "readiness"
    assert investigations.resolve(store, "Reviewer", req) == result
    record, = [e for e in investigations.inventory(store, project)["experiments"] if e["id"] == experiment]
    assert record["requests"][0]["resources"][0]["briefing"] == resource["briefing"]
    assert [r["id"] for r in record["resources"]] == [resource["id"]]


CARY_ID = "agilent-cary-60-user-guide"
CARY_OBJECTIVE = "Check wavelength accuracy on the Agilent Cary 60"


def _procedure(store, objective, project="proj"):
    return investigations.resolve(store, "R", request(project, objective, kind="procedure"))["resources"][-1]


def _project_lab(store):
    _lab_project(store)
    return store.get_experiment("proj")[0].lab_id


def test_new_procedure_pins_shared_text_for_a_matched_source(store, monkeypatch):
    from labfactory import library, source_drafter
    monkeypatch.setattr(source_drafter, "available", lambda: True)
    from labfactory.workorders import WorkOrders
    _project_lab(store)
    entry = library.add(store, "Ana", "Wavelength accuracy is checked with the internal filter.", source_id=CARY_ID)
    resource = _procedure(store, CARY_OBJECTIVE)
    assert resource["library"] == [{"document_id": "library:" + CARY_ID, "source_id": CARY_ID, "title": entry["title"],
                                    "scope": "shared", "entry_id": entry["id"], "revision": 1}]
    refs = {r["id"]: r for r in resource["briefing"]["references"]}
    assert refs[CARY_ID]["document_id"] == "library:" + CARY_ID
    findings = briefing.load(store, resource["id"])["reference_library"]["findings"]
    assert [f["id"] for f in findings if "document_id" in f] == [CARY_ID]
    lab, experiment = WorkOrders(store).pinned_context(resource["id"])
    assert experiment.documents[0].id == "library:" + CARY_ID
    assert resource["status"] == "drafting"
    children = [r["id"] for r in store.connection.execute("SELECT DISTINCT id FROM records WHERE kind='experiment' AND id LIKE 'investigation-%'")]
    assert children and all(store.get_experiment(i)[0].documents == () for i in children)


def test_pinned_text_without_a_drafter_still_asks_at_once(store, monkeypatch):
    from labfactory import library, source_drafter
    from labfactory.workorders import WorkOrders
    monkeypatch.setattr(source_drafter, "available", lambda: False)
    _project_lab(store)
    entry = library.add(store, "Ana", "Wavelength accuracy is checked with the internal filter.", source_id=CARY_ID)
    resource = _procedure(store, CARY_OBJECTIVE)
    assert resource["status"] == "needs_input"
    assert [item["entry_id"] for item in resource["library"]] == [entry["id"]]
    _, experiment = WorkOrders(store).pinned_context(resource["id"])
    assert experiment.documents[0].id == "library:" + CARY_ID


def test_real_documents_still_go_to_the_drafter_when_none_is_available(store, monkeypatch):
    from labfactory import first_draft, procedure_drafts, source_drafter
    monkeypatch.setattr(source_drafter, "available", lambda: False)
    lab_id = _project_lab(store)
    experiment, _ = store.get_experiment("proj")
    doc = Document("method-1", "note", "Own notes", "me", "Some prose that is not a method.")
    store.put_experiment(replace(experiment, documents=(doc,)), allow_unassigned=True)
    order = procedure_drafts.create(store, "proj", "R")
    data = {"request_id": "r1"}
    assert first_draft._compile(store, order, "R", data, "fp", None)["state"] == "drafting"


def test_worker_draft_path_pins_library_text(store):
    from labfactory import library
    _project_lab(store)
    entry = library.add(store, "Ana", "Wavelength accuracy is checked with the internal filter.", source_id=CARY_ID)
    resource = _procedure(store, "Ask a worker to draft a procedure to check wavelength accuracy on the Agilent Cary 60")
    assert [item["entry_id"] for item in resource["library"]] == [entry["id"]]
    assert resource["briefing"]["references"][0]["document_id"] == "library:" + CARY_ID
    findings = briefing.load(store, resource["id"])["reference_library"]["findings"]
    assert [f["id"] for f in findings if f.get("document_id") == "library:" + CARY_ID] == [CARY_ID]


def test_colliding_library_document_is_not_claimed(store):
    from labfactory import library
    from labfactory.context import Document
    _project_lab(store)
    root, _ = store.get_experiment("proj")
    store.put_experiment(replace(root, documents=(Document("library:" + CARY_ID, "note", "Mine", "me", "Mine."),)))
    library.add(store, "Ana", "Wavelength accuracy is checked with the internal filter.", source_id=CARY_ID)
    resource = _procedure(store, CARY_OBJECTIVE)
    assert "library" not in resource
    assert not any("document_id" in f for f in briefing.load(store, resource["id"])["reference_library"]["findings"])


def test_pinned_text_is_capped_in_total_size(store, monkeypatch):
    from labfactory import library
    assert library.MAX_PINNED_BYTES == 512 * 1024
    monkeypatch.setattr(library, "MAX_PINNED_BYTES", 1000)
    _project_lab(store)
    first = library.add(store, "Ana", "Wavelength accuracy. " + "x" * 600, source_id=CARY_ID)
    library.add(store, "Ana", "Moisture. " + "x" * 600, source_id="ihc-2009-honey-moisture")
    small = library.add(store, "Ana", "Small note.", title="Wavelength accuracy checklist", lab_id="lab")
    brief = {"reference_library": {"findings": [{"id": CARY_ID}, {"id": "ihc-2009-honey-moisture"}]}}
    entries = investigations._library_entries(store, "lab", brief, "Wavelength accuracy checklist")
    assert [e["id"] for e in entries] == [first["id"], small["id"]]
    assert sum(e["bytes"] for e in entries) <= library.MAX_PINNED_BYTES


def test_library_read_failure_after_the_transaction_ended_is_not_hidden(store):
    import sqlite3
    class Gone:
        in_transaction = False
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("gone")
    store.connection, real = Gone(), store.connection
    try:
        with pytest.raises(sqlite3.OperationalError):
            investigations._library_entries(store, "lab", {"reference_library": {"findings": [{"id": CARY_ID}]}}, "x")
    finally:
        store.connection = real


def test_new_procedure_pins_the_labs_own_contributed_text(store, monkeypatch):
    from labfactory import source_drafter
    monkeypatch.setattr(source_drafter, "available", lambda: True)
    from labfactory import library
    lab_id = _project_lab(store)
    library.add(store, "Ana", "Zero the archive balance before use.", title="Archive balance worksheet", lab_id=lab_id)
    resource = _procedure(store, "Draft a procedure to weigh samples with the archive balance worksheet")
    item, = resource["library"]
    assert item["scope"] == "lab" and item["document_id"].startswith("library:contributed-")


def test_contributed_text_needs_two_matching_title_terms(store):
    from labfactory import library
    lab_id = _project_lab(store)
    library.add(store, "Ana", "Zero the archive balance before use.", title="Archive balance worksheet", lab_id=lab_id)
    assert "library" not in _procedure(store, "Draft a procedure for the balance")


def test_another_labs_private_text_is_not_pinned(store):
    from labfactory import library
    _project_lab(store)
    library.add(store, "Ana", "Private note.", source_id=CARY_ID, lab_id="other-lab")
    resource = _procedure(store, CARY_OBJECTIVE)
    assert "library" not in resource and resource["status"] == "needs_input"


def test_no_library_text_leaves_the_investigation_unchanged(store):
    _project_lab(store)
    resource = _procedure(store, CARY_OBJECTIVE)
    assert "library" not in resource and resource["status"] == "needs_input"
    assert not any("document_id" in f for f in briefing.load(store, resource["id"])["reference_library"]["findings"])


def test_library_failure_does_not_fail_the_investigation(store, monkeypatch):
    import sqlite3
    from labfactory import library
    _project_lab(store)
    library.add(store, "Ana", "Some text.", source_id=CARY_ID)

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(library, "visible", broken)
    resource = _procedure(store, CARY_OBJECTIVE)
    assert "library" not in resource


def test_new_app_never_pins_library_text(store):
    from labfactory import library
    _project_lab(store)
    library.add(store, "Ana", "Honey moisture by refractometry.", source_id="ihc-2009-honey-moisture")
    result = investigations.resolve(store, "R", request(
        "proj", "Analyze the honey moisture readings by refractometry", kind="app"))
    resource = result["resources"][-1]
    assert "library" not in resource
    assert not any("document_id" in r for r in resource.get("briefing", {}).get("references", []))
