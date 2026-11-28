from uuid import uuid4

import pytest

from labfactory import analysis_requests, investigations, research_experiments, tabular_service
from labfactory.context import ContextError
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
    named = followup("Plot this dataset against sibling.csv", app="new")
    assert named["resources"][0]["id"] == other + "/uploads/readings"
    clarified = followup("Summarize this dataset", app="new")
    assert clarified["field"] == "data"
    assert {o["id"] for o in clarified["options"]} == {data["id"], other + "/uploads/readings", "new"}
    inv = investigations.inventory(store, project)
    assert data["id"] in {r["id"] for r in inv["experiments"][0]["resources"]}


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
    orders.submit(first.id, "Worker", {"needs_input": "Which record should be checked?"})
    revision = procedure_drafts.add_source(store, first.id, "Reviewer", "Worksheet", "Check the archived entries.")
    view = investigations.inventory(store, project)
    assert [r["id"] for r in view["resources"]] == [revision]
    original, = view["experiments"][0]["resources"]
    assert original["id"] == first.id and original["next_order"] == revision


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
