import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest

from labfactory import references, tabular_service as svc
from labfactory.agent import AgentTools
from labfactory.context import ContextError, canonical_digest, canonical_json, experiment_from_dict, lab_from_dict
from labfactory.store import Store
from labfactory.workorders import WorkOrderError, WorkOrders


@pytest.fixture
def request_data():
    return {
        "objective": "Estimate original sample concentration", "protocol": "Use the calibration and row factor.\r\n",
        "protocol_name": "méthode.md", "csv_name": "private_batch.csv", "unit": "mg/L original",
        "mapping": {"id": "vial", "role": "kind", "signal": "area", "known": "standard level", "factor": "factor"},
        "control_expected": 5.392, "control_tolerance": 0.0137,
        "csv": "\ufeffvial,kind,area,standard level,factor\r\ns1,standard,10,1,1\r\ns2,standard,100,10,1\r\n"
               'private-control-vial,control,53.92,,1\r\n"unknown,trial A",unknown,70.123,,2\r\n',
    }


def _artifact(multiplier=1):
    return {"source": f"def analyze(standards, signal, factor):\n    return signal * factor * {multiplier} / 10",
            "explanation": "Convert response to original concentration.", "tests": [
                {"label": "Equal volume", "standards": [], "signal": 20, "factor": 1, "expected": 2 * multiplier},
                {"label": "Dilution", "standards": [], "signal": 60, "factor": 2, "expected": 12 * multiplier},
            ]}


def _create(store, request_data):
    return svc.create_order(store, "Reviewer", request_data)["id"]


@pytest.mark.parametrize("corrupt", [
    "DELETE FROM events WHERE work_order_id=? AND event='approved'",
    "UPDATE events SET note='wrong digest' WHERE work_order_id=? AND event='approved'",
    "UPDATE submissions SET artifact='{}' WHERE work_order_id=?",
    "UPDATE submissions SET passed=0 WHERE work_order_id=?",
    "UPDATE submissions SET results='[]' WHERE work_order_id=?",
])
def test_link_requires_verifiable_procedure_release(store, request_data, uvvis_lab_dict, b12_experiment_dict, corrupt):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    experiment = experiment_from_dict(b12_experiment_dict)
    store.put_experiment(experiment)
    orders = WorkOrders(store)
    order = orders.create(experiment.id, "procedure", "Review optical handling")
    orders.claim(order.id, "Author")
    orders.submit(order.id, "Author", {"steps": [{"text": "Record the reading.", "citations": ["sop-cuvette"]}]})
    orders.approve(order.id, "Reviewer", 1)
    store.connection.execute(corrupt, (order.id,))
    with pytest.raises(WorkOrderError, match="approved artifact"):
        _create(store, {**request_data, "procedure_order_id": order.id})
    assert svc.catalog(store) == {"orders": []}


def test_opaque_author_context_and_originals(store, request_data):
    request_data["reference_ids"] = ["ihc-2009-honey-moisture"]
    key = _create(store, request_data)
    context = AgentTools(store).get_work_order_context(key)
    assert context["analysis"]["standards"] == [[10, 1], [100, 10]]
    assert context["analysis"]["references"] == [references.source("ihc-2009-honey-moisture")]
    encoded = json.dumps(context)
    for private in ("5.392", "0.0137", "53.92", "70.123", "unknown,trial A", "private-control-vial", "private_batch.csv"):
        assert private not in encoded
    assert svc.original(store, key, "readings") == ("private_batch.csv", request_data["csv"])
    assert svc.original(store, key, "protocol") == ("méthode.md", request_data["protocol"])
    assert context["analysis"]["protocol_digest"] == svc.tabular_files.digest(request_data["protocol"])
    with pytest.raises(WorkOrderError, match="upload"):
        WorkOrders(store).create(context["experiment"]["id"], "analysis_app", "bypass")
    assert len(svc.catalog(store)["orders"]) == 1


def test_blind_attempt_pinned_reviewer_and_separate_qc_for_revised_source(store, request_data):
    key = _create(store, request_data)
    agent = AgentTools(store)
    agent.claim_work_order(key, "Worker")
    first = agent.submit_artifact(key, "Worker", _artifact(2))
    assert not first["passed"] and first["submission"] == 1
    assert all(r["passed"] for r in first["results"] if "Agent test" in r["name"])
    assert not any(v in json.dumps(first) for v in ("5.392", "0.0137", "53.92", "10.784"))
    assert agent.get_work_order_context(key)["analysis"]["awaiting_fresh_control"]
    assert "fresh blind" in agent.submit_artifact(key, "Worker", _artifact())["error"]
    assert len(WorkOrders(store).submissions(key)) == 1
    with pytest.raises(WorkOrderError):
        WorkOrders(store).approve(key, "Reviewer", 1)
    replacement = {"signal": 47.36, "factor": 1, "expected": 4.736, "tolerance": .01}
    with pytest.raises(ContextError, match="newly measured"):
        svc.replace_control(store, key, "Reviewer", {**replacement, "signal": 53.92})
    svc.replace_control(store, key, "Reviewer", replacement)
    second = agent.submit_artifact(key, "Worker", _artifact())
    assert second["passed"] and second["submission"] == 2
    WorkOrders(store).reject(key, "Reviewer", 2, "This PRIVATE 4.736 target must never reach the author")
    public = agent.get_work_order_context(key)
    assert "PRIVATE" not in json.dumps(public) and "4.736" not in json.dumps(public)
    assert public["previous_rejection"]["artifact"] == _artifact() and public["analysis"]["awaiting_fresh_control"]
    svc.replace_control(store, key, "Reviewer", {**replacement, "signal": 66.44, "expected": 6.644})
    agent.claim_work_order(key, "Second agent")
    assert agent.submit_artifact(key, "Second agent", _artifact())["passed"]
    WorkOrders(store).approve(key, "Reviewer", 3)
    receipt = svc.run(store, key, "Reviewer", {"submission": 3})
    assert receipt["results"][0]["value"] == pytest.approx(14.0246)
    assert receipt["release_control_edition"] == 3
    assert receipt["control"]["source"] == "original batch" and receipt["control"]["edition"] == 1
    assert receipt["control"]["signal"] == 53.92
    assert receipt["artifact_digest"] == canonical_digest(_artifact()) and receipt["status"] == "estimated"


def test_original_batch_qc_withholds_after_a_passing_replacement_and_checks_exact_reuploads(store, request_data):
    request_data["control_expected"] = 6.0  # Final method predicts 5.392 for this collected QC sample.
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "Writer")
    assert not orders.submit(key, "Writer", _artifact(2)).passed
    replacement = {"signal": 40, "factor": 1, "expected": 4, "tolerance": .02}
    svc.replace_control(store, key, "R", replacement)
    assert orders.submit(key, "Writer", _artifact()).passed
    orders.approve(key, "R", 2)

    # Simulate the persisted run identity from before collected and release controls were separated.
    _, batch = svc._intake(store, key)
    old_digest = canonical_digest({"batch": batch, "control": {k: float(v) for k, v in replacement.items()}})
    old_receipt = {"batch_digest": old_digest, "csv_name": batch["csv_name"], "csv_digest": batch["csv_digest"],
                   "status": "estimated", "control": {"source": "replacement blind control", "edition": 2}}
    with store.transaction() as db:
        db.execute("INSERT INTO tabular_runs(work_order_id,submission,batch_digest,actor,receipt) VALUES (?,?,?,?,?)",
                   (key, 2, old_digest, "R", canonical_json(old_receipt)))

    run = svc.run(store, key, "R", {"submission": 2})
    assert run["status"] == "withheld" and run["results"] == []
    assert run["release_control_edition"] == 2
    assert run["control"]["edition"] == 1 and not run["control"]["passed"]
    assert (run["control"]["expected"], run["control"]["predicted"]) == pytest.approx((6, 5.392))
    reupload = {k: request_data[k] for k in ("csv", "control_expected", "control_tolerance")}
    reupload.update(submission=2, csv_name="renamed.csv")
    assert svc.run(store, key, "R", reupload) == run
    with pytest.raises(WorkOrderError, match="already pinned"):
        svc.run(store, key, "R", {**reupload, "control_expected": 5.392})
    archived = svc.list_runs(store.connection, key)
    assert len(archived) == 2 and archived[1]["batch_digest"] == old_digest and archived[1]["status"] == "estimated"

    with store.transaction() as db:
        db.execute("UPDATE tabular_controls SET value=? WHERE work_order_id=? AND edition=1",
                   (canonical_json(replacement), key))
    with pytest.raises(WorkOrderError, match="sealed"):
        svc.run(store, key, "R", {"submission": 2})


def test_public_clarification_and_syntax_failures_do_not_consume_holdout(store, request_data):
    key = _create(store, request_data)
    agent = AgentTools(store)
    agent.claim_work_order(key, "Writer")
    missing = {"needs_input": "What dilution factor applies to the original sample?"}
    assert not agent.submit_artifact(key, "Writer", missing)["passed"]
    assert agent.get_work_order_context(key)["analysis"]["needs_input"] == missing["needs_input"]
    assert not agent.submit_artifact(key, "Writer", {"source": "pass"})["passed"]
    assert not agent.get_work_order_context(key)["analysis"]["awaiting_fresh_control"]
    assert agent.submit_artifact(key, "Writer", _artifact())["passed"]
    with pytest.raises(WorkOrderError):
        svc.replace_control(store, key, "R", {"signal": 60,"factor": 1,"expected": 6,"tolerance": .02})


def test_batch_rerun_freezes_control_per_upload_and_actor(store, request_data):
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "W")
    assert orders.submit(key, "W", _artifact()).passed
    with pytest.raises(WorkOrderError, match="Approve"):
        svc.run(store, key, "R", {"submission": 1})
    orders.approve(key, "R", 1)
    new_batch = {k: request_data[k] for k in ("csv_name", "csv", "control_expected", "control_tolerance")}
    with pytest.raises(WorkOrderError, match="already pinned"):
        svc.run(store, key, "R", {**new_batch, "submission": 1, "control_tolerance": 1000.0})
    new_batch.update(csv=new_batch["csv"].replace("53.92", "53.93"), control_expected=90, submission=1)
    receipt = svc.run(store, key, "R", new_batch)
    assert receipt["status"] == "withheld" and not receipt["results"]
    assert not receipt["control"]["passed"] and receipt["control"]["expected"] == 90
    assert svc.run(store, key, "R", new_batch) == receipt
    assert svc.run_original(store, key, receipt["id"]) == (request_data["csv_name"], new_batch["csv"])
    with pytest.raises(WorkOrderError, match="pinned"):
        svc.run(store, key, "Another", {**new_batch, "control_expected": 5.393})
    with pytest.raises(WorkOrderError, match="Approve"):
        svc.run(store, key, "R", {"submission": 2})
    with store.transaction() as db:
        db.execute("UPDATE events SET note='modified' WHERE work_order_id=? AND event='approved'", (key,))
    with pytest.raises(WorkOrderError, match="digest"):
        svc.run(store, key, "R", {"submission": 1})


def test_reviewer_approval_checks_immutable_control_digest(store, request_data):
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "W")
    sub = orders.submit(key, "W", _artifact())
    assert sub.passed
    with store.transaction() as db:
        db.execute("UPDATE tabular_controls SET value=? WHERE work_order_id=?", (
            canonical_json({"signal": 53.92, "factor": 1, "expected": 5.392, "tolerance": 70}), key))
    with pytest.raises(WorkOrderError, match="sealed"):
        orders.approve(key, "R", 1)


def test_retried_creation_and_concurrent_sealed_attempts(tmp_path, request_data):
    db_file = tmp_path / "retry.sqlite"
    request_data["request_id"] = str(uuid4())
    with Store(db_file) as store:
        key = _create(store, request_data)
        assert _create(store, request_data) == key
        with pytest.raises(WorkOrderError, match="different upload"):
            _create(store, {**request_data, "objective": "Different"})
        WorkOrders(store).claim(key, "W")
    def submit():
        with Store(db_file) as store:
            return AgentTools(store).submit_artifact(key, "W", _artifact(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: submit(), range(2)))
    assert sum("error" in r for r in replies) == 1
    with Store(db_file) as store:
        assert len(WorkOrders(store).submissions(key)) == 1


@pytest.mark.parametrize(("field","value"), [
    ("csv", "vial,kind,area,area,factor\n"), ("protocol", "a" * (32 * 1024 + 1)),
    ("protocol", "bad\udc00"), ("protocol_name", "../x.md"), ("unit", ""),
    ("control_tolerance", -0.01), ("control_expected", "NaN"), ("range_gate", 0),
    ("reference_ids", ["missing"]), ("request_id", "wrong"),
])
def test_invalid_upload_rolls_back(store, request_data, field, value):
    with pytest.raises(ContextError):
        _create(store, {**request_data, field: value})
    assert not svc.catalog(store)["orders"]


def test_rejects_private_value_in_csv_missing_factor_and_duplicate_headers(store, request_data):
    variants = [
        request_data["csv"].replace("53.92,,1", "53.92,5.392,1"),
        request_data["csv"].replace("70.123,,2", "70.123,,"),
        request_data["csv"].replace("s2,standard", "s1,standard"),
        request_data["csv"].replace("53.92,,1", "53.92,,1,extraneous"),
        request_data["csv"].replace("s2,standard,100,10,1", "s2,standard,100,10,2"),
    ]
    for raw in variants:
        with pytest.raises(ContextError):
            _create(store, {**request_data, "csv": raw})
    assert not svc.catalog(store)["orders"]


@pytest.mark.parametrize("corruption", ["mapping", "protocol", "standards", "unknown", "csv_digest"])
def test_private_intake_stamp_guards_review_and_runs_after_release(store, request_data, corruption):
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "W")
    assert orders.submit(key, "W", _artifact()).passed
    orders.approve(key, "R", 1)
    with store.transaction() as db:
        row = db.execute("SELECT profile,batch FROM tabular_intakes WHERE work_order_id=?", (key,)).fetchone()
        profile, batch = json.loads(row["profile"]), json.loads(row["batch"])
        if corruption == "mapping":
            profile["mapping"]["signal"] = "other signal"
        elif corruption == "protocol":
            profile["protocol_digest"] = "a" * 64
        elif corruption == "standards":
            batch["standards"][0][1] += .1
        elif corruption == "unknown":
            batch["unknowns"][0]["signal"] += 1
        else:
            batch["csv_digest"] = "0" * 64
        db.execute("UPDATE tabular_intakes SET profile=?, batch=? WHERE work_order_id=?",
                   (canonical_json(profile), canonical_json(batch), key))
    with pytest.raises(WorkOrderError, match="pinned intake"):
        svc.run(store, key, "R", {"submission": 1})
    assert "pinned intake" in AgentTools(store).get_work_order_context(key)["error"]


def test_public_experiment_binding_is_checked_at_approval_without_mcp_read(store, request_data):
    key = _create(store, request_data)
    orders = WorkOrders(store)
    orders.claim(key, "W")
    assert orders.submit(key, "W", _artifact()).passed
    changed = deepcopy(request_data)
    changed["protocol"] = "An alternative protocol"
    other = _create(store, changed)
    with store.transaction() as db:
        db.execute("UPDATE work_orders SET experiment_id=? WHERE id=?", (orders.get(other).experiment_id, key))
    with pytest.raises(WorkOrderError, match="pinned experiment"):
        orders.approve(key, "R", 1)


def test_private_downloads_require_reviewer_and_return_exact_originals(tmp_path, monkeypatch, request_data):
    from starlette.testclient import TestClient
    from labfactory.hosted import application
    from labfactory.hosted_auth import password_hash, token_digest

    dbfile = tmp_path / "isolated.db"
    monkeypatch.setenv("LABFACTORY_LOCAL_DB", str(dbfile))
    monkeypatch.setenv("LABFACTORY_SESSION_KEY", "a-local-test-only-tabular-signing-key")
    monkeypatch.setenv("LABFACTORY_REVIEWERS", json.dumps({"User": password_hash("test-only-login")}))
    monkeypatch.setenv("LABFACTORY_AGENTS", json.dumps({"Writer": token_digest("test-only-agent")}))
    monkeypatch.delenv("VERCEL", raising=False)
    with Store(dbfile) as store:
        key = _create(store, request_data)
    origin = "https://localhost"
    path = "/api/analysis/orders/" + key
    with TestClient(application, base_url=origin, headers={"Origin": origin}) as client:
        for url in [path, path + "/uploads/protocol", path + "/uploads/readings", path + "/runs/1/readings"]:
            assert client.get(url).status_code == 401
            assert client.get(url, headers={"Authorization": "Bearer test-only-agent"}).status_code == 401
        client.post("/api/login", json={"name": "User", "password": "test-only-login"}).raise_for_status()
        for kind, expected in [("protocol", request_data["protocol"]), ("readings", request_data["csv"])]:
            response = client.get(path + "/uploads/" + kind).raise_for_status()
            assert response.content == expected.encode()
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
        assert client.get(path + "/uploads/unknown").status_code == 404
        assert client.get(path + "/runs/1/readings").status_code == 404
        assert client.post(path + "/runs", json={"submission": 1}).status_code == 409


def test_created_order_pins_enabled_skill_in_actual_author_request(store, request_data, monkeypatch):
    from types import SimpleNamespace
    from labfactory import tabular_worker

    supplied = {"id": "record-links", "name": "Record links", "whenToUse": "When inspecting a run.",
                "instructions": "Trace each specimen to its signed acquisition."}
    request_data["skills"] = [supplied]
    key = _create(store, request_data)
    supplied["instructions"] = "Later revision."
    context = AgentTools(store).get_work_order_context(key)
    pinned, = context["analysis"]["skills"]
    assert pinned["instructions"] == "Trace each specimen to its signed acquisition."
    assert context["analysis"]["skill_versions"] == [{"id": supplied["id"], "version": pinned["version"]}]
    assert len(pinned["version"]) == 64
    assert svc.reviewer_context(store, WorkOrders(store).get(key))["skills"] == [pinned]

    def capture(prompt, *args, **kwargs):
        payload = json.loads(prompt.splitlines()[-1])
        assert payload["enabledSkills"] == [pinned]
        assert "Later revision." not in prompt
        return SimpleNamespace(answer={"question": "Which procedure applies?"})

    monkeypatch.setattr(tabular_worker, "run_worker", capture)
    assert tabular_worker.generate(context) == {"needs_input": "Which procedure applies?"}

    with pytest.raises(ContextError):
        _create(store, {**request_data, "skills": [{**supplied, "version": pinned["version"]}]})
    assert len(svc.catalog(store)["orders"]) == 1


def test_pinned_language_checked_before_holdout_and_reused_after_release(store, request_data):
    key = _create(store, {**request_data, "allowed_languages": ["matlab"]})
    agent = AgentTools(store)
    context = agent.get_work_order_context(key)
    assert context["analysis"]["allowed_languages"] == ["matlab"]
    assert context["analysis"]["verifiers"] == {"matlab": "bounded-matlab-scalar-v1"}
    assert "interp1" in context["instructions"] and "def analyze" not in context["instructions"]
    agent.claim_work_order(key, "Worker")
    artifact = _artifact()
    for wrong in (artifact, {**artifact, "language": "python"}, {**artifact, "language": "matlab"}):
        assert not agent.submit_artifact(key, "Worker", wrong)["passed"]
        assert not agent.get_work_order_context(key)["analysis"]["awaiting_fresh_control"]
    artifact.update(language="matlab", source="function result = analyze(standards, signal, factor)\n"
                                              "result = signal * factor / 10;\nend")
    submitted = agent.submit_artifact(key, "Worker", artifact)
    assert submitted["passed"]
    number = submitted["submission"]
    WorkOrders(store).approve(key, "Reviewer", number)
    receipt = svc.run(store, key, "Reviewer", {"submission": number})
    assert receipt["control"]["verifier"] == "bounded-matlab-scalar-v1"
    assert receipt["language"] == "matlab" and receipt["results"][0]["value"] == pytest.approx(14.0246)


@pytest.mark.parametrize("languages", [None, [], "matlab", ["matlab", "matlab"], ["r"], [{}]])
def test_language_constraints_validated_at_intake(store, request_data, languages):
    with pytest.raises(ContextError, match="allowed_languages"):
        _create(store, {**request_data, "allowed_languages": languages})
