from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
from threading import Barrier

import pytest

from labfactory import b12_service as service
from labfactory.context import ContextError, canonical_digest
from labfactory.store import NotFound, Store, _SCHEMA
from labfactory.workorders import WorkOrderError, WorkOrders


SOURCE = """def analyze(readings, slope, intercept):
    average = sum(readings) / len(readings)
    return (average - intercept) / slope
"""


def submitted(store, order_id):
    orders = WorkOrders(store)
    orders.claim(order_id, "agent")
    candidate = orders.submit(order_id, "agent", {"source": SOURCE})
    assert candidate.passed, candidate.results
    return candidate


def test_records_before_release_and_idempotent_execution(store):
    order = service.create_order(store, "Sam")["id"]
    assert service.catalog(store)["orders"][0]["id"] == order
    readings = service.save_readings(store, order, "Sam", [0.1020, 0.1024, 0.1028])
    assert readings["actor"] == "Sam" and readings["result"] is None
    candidate = submitted(store, order)
    with pytest.raises(WorkOrderError, match="released"):
        service.run_readings(store, order, readings["id"], "Sam", candidate.number)
    assert service.list_readings(store, order)["readings"] == [readings]
    WorkOrders(store).approve(order, "Casey", candidate.number)
    result = service.run_readings(store, order, readings["id"], "Sam", candidate.number)
    assert result["status"] == "estimated" and result["concentration_mg_l"] == pytest.approx(16.0)
    assert result["calibration_id"] == service.CALIBRATION["id"]
    assert result["readings_digest"] == canonical_digest(readings["readings"])
    assert result["worker"] == "agent" and result["approved_by"] == "Casey"
    assert result["artifact_digest"] == candidate.artifact_digest and result["submission"] == 1
    assert result["lab_revision"] == result["experiment_revision"] == 1
    assert service.run_readings(store, order, readings["id"], "another reviewer", 1) == result
    assert service.list_readings(store, order)["readings"][0]["result"] == result
    with pytest.raises(WorkOrderError, match="released"):
        service.run_readings(store, order, readings["id"], "Sam", 2)
    with pytest.raises(ContextError):
        service.run_readings(store, order, readings["id"], "Sam", True)
    high = service.save_readings(store, order, "Sam", [0.12, 0.12, 0.16])
    withheld = service.run_readings(store, order, high["id"], "Sam", 1)
    assert withheld["status"] == "withheld" and withheld["concentration_mg_l"] is None


def test_pinned_calibration_and_source_integrity(store):
    order = service.create_order(store, "reviewer")["id"]
    orders = WorkOrders(store)
    lab, exp = orders.pinned_context(order)
    doc = replace(exp.documents[0], text="New curve")
    store.put_experiment(replace(exp, documents=(doc,)))
    assert not all(check.passed for check in service.calibration_checks(lab, store.get_experiment(exp.id)[0]))
    with pytest.raises(WorkOrderError, match="pinned"):
        service.create_order(store, "reviewer")
    assert len(service.catalog(store)["orders"]) == 1
    candidate = submitted(store, order)
    orders.approve(order, "reviewer", candidate.number)
    readings = service.save_readings(store, order, "operator", [0.10] * 3)
    # A corrupted source must never run under the approved digest.
    with store.transaction() as db:
        db.execute("UPDATE submissions SET artifact=? WHERE work_order_id=?",
                   (json.dumps({"source": SOURCE + "# changed\n"}), order))
    with pytest.raises(WorkOrderError, match="digest"):
        service.run_readings(store, order, readings["id"], "operator", candidate.number)
    assert service.list_readings(store, order)["readings"][0]["result"] is None


def test_order_and_reading_isolation_and_validation(store):
    order = service.create_order(store, "reviewer")["id"]
    other = service.create_order(store, "reviewer")["id"]
    old = WorkOrders(store).create(service.EXPERIMENT_ID, "run_plan", "Read absorbance")
    for invalid in ([], [True, 0.1, 0.1], [0.1, 0.1, float("nan")]):
        with pytest.raises(ContextError):
            service.save_readings(store, order, "R", invalid)
    with pytest.raises(WorkOrderError, match="simulated B12 analysis order"):
        service.save_readings(store, old.id, "R", [.1] * 3)
    reading = service.save_readings(store, order, "R", [.1] * 3)
    submitted(store, other)
    WorkOrders(store).approve(other, "R", 1)
    with pytest.raises(NotFound):
        service.run_readings(store, other, reading["id"], "R", 1)
    assert service.list_readings(store, other)["readings"] == []


@pytest.mark.parametrize(("field", "replacement"), [("id", "b12-new-version"), ("slope_au_per_mg_l", 0.008)])
def test_current_evaluator_cannot_change_an_approved_calibration(store, monkeypatch, field, replacement):
    order = service.create_order(store, "R")["id"]
    candidate = submitted(store, order)
    WorkOrders(store).approve(order, "R", candidate.number)
    first = service.save_readings(store, order, "R", [.1024] * 3)
    second = service.save_readings(store, order, "R", [.1] * 3)
    completed = service.run_readings(store, order, first["id"], "R", 1)
    pinned = dict(service.CALIBRATION)
    monkeypatch.setitem(service.CALIBRATION, field, replacement)
    with pytest.raises(WorkOrderError, match="pinned"):
        service.run_readings(store, order, second["id"], "R", 1)
    details = service.list_readings(store, order)
    assert details["calibration"] == completed["calibration"] == pinned
    assert completed["calibration_digest"] == canonical_digest(pinned)
    assert details["readings"][0]["result"] is None
    assert service.run_readings(store, order, first["id"], "R", 1) == completed


def test_concurrent_runs_persist_one_result(tmp_path):
    path = tmp_path / "runs.db"
    with Store(path) as store:
        order = service.create_order(store, "R")["id"]
        submitted(store, order)
        WorkOrders(store).approve(order, "R", 1)
        record = service.save_readings(store, order, "R", [.1024] * 3)
    barrier = Barrier(2)

    def calculate(reviewer):
        with Store(path) as store:
            barrier.wait(timeout=5)
            return service.run_readings(store, order, record["id"], reviewer, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(calculate, ("R", "S")))
    assert first == second
    with Store(path) as reopened:
        assert reopened.connection.execute("SELECT count(*) FROM b12_results").fetchone()[0] == 1
        assert service.list_readings(reopened, order)["readings"][0]["result"] == first


def test_legacy_database_upgrade_preserves_ids_and_release_history(tmp_path):
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for name, ddl in _SCHEMA.items():
            if not name.startswith("b12_"):
                db.execute(ddl.replace(",'analysis_app'", ""))
        db.execute("""INSERT INTO work_orders(rowid,id,experiment_id,experiment_revision,lab_id,lab_revision,
                   kind,objective,status,worker) VALUES(5,'WO-5','b12-vial-a',2,'legacy-lab',3,
                   'run_plan','original objective','released','A')""")
        db.execute("""INSERT INTO submissions(work_order_id,number,worker,artifact,artifact_digest,results,passed)
                   VALUES('WO-5',2,'A','{}','previous-digest','[]',1)""")
        db.execute("UPDATE work_orders SET released_submission=2 WHERE id='WO-5'")
        db.execute("""INSERT INTO events(rowid,work_order_id,event,actor,submission,note)
                   VALUES(11,'WO-5','approved','R',2,'previous-digest')""")
        assert "'analysis_app'" not in db.execute("SELECT sql FROM sqlite_master WHERE name='work_orders'").fetchone()[0]
    barrier = Barrier(2)

    def reopen(_):
        barrier.wait(timeout=5)
        with Store(path) as store:
            return service.create_order(store, "R")["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reopen, range(2))) == ["WO-6", "WO-7"]
    with Store(path) as upgraded:
        db = upgraded.connection
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        old = WorkOrders(upgraded).get("WO-5")
        assert (old.experiment_revision, old.lab_revision, old.released_submission) == (2, 3, 2)
        assert old.status == "released"
        assert tuple(db.execute("SELECT rowid,note,actor FROM events WHERE work_order_id='WO-5'").fetchone()) == (
            11, "previous-digest", "R",
        )
        assert WorkOrders(upgraded).submission("WO-5", 2).artifact_digest == "previous-digest"
