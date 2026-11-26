from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest

from labfactory.agent import AgentTools
from labfactory.artifacts import ARTIFACT_EXAMPLES, ArtifactError
from labfactory.context import canonical_digest, experiment_from_dict, lab_from_dict
from labfactory.store import Store
from labfactory.workorders import WorkOrder, WorkOrderError, WorkOrders


@pytest.fixture
def orders(store, uvvis_lab_dict, b12_experiment_dict):
    store.put_lab(lab_from_dict(uvvis_lab_dict))
    store.put_experiment(experiment_from_dict(b12_experiment_dict))
    return WorkOrders(store)


def create(orders):
    return orders.create("b12-vial-a", "run_plan", "Read absorbance")


def plan(value=550):
    artifact = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    artifact["steps"][0]["settings"][0]["value"] = value
    return artifact


def test_create_pins_current_revisions(orders):
    order = create(orders)
    assert (order.id, order.status, order.released_submission) == ("WO-1", "open", None)
    assert order.lab_revision == order.experiment_revision == 1
    assert create(orders).id == "WO-2"
    assert orders.list("open") == orders.list() == [order, orders.get("WO-2")]
    with pytest.raises(WorkOrderError, match="kind"):
        orders.create("b12-vial-a", "software", "Analyze")


def test_create_rejects_incompatible_context_without_changing_prior_pins(orders, store, uvvis_lab_dict):
    old = create(orders)
    original = lab_from_dict(uvvis_lab_dict)
    uvvis_lab_dict["instruments"] = []
    store.put_lab(lab_from_dict(uvvis_lab_dict))

    with pytest.raises(WorkOrderError, match="unknown instrument uvvis-1"):
        create(orders)
    assert orders.list() == [old]
    orders.claim(old.id, "codex")
    assert orders.submit(old.id, "codex", plan()).passed

    assert store.put_lab(original).number == 3
    new = create(orders)
    assert (new.id, new.lab_revision) == ("WO-2", 3)


def test_agent_reads_committed_state_during_write(tmp_path, uvvis_lab_dict, b12_experiment_dict):
    path = tmp_path / "review.db"
    with Store(path) as writer:
        writer.put_lab(lab_from_dict(uvvis_lab_dict))
        writer.put_experiment(experiment_from_dict(b12_experiment_dict))
        order = create(WorkOrders(writer))
        with writer.transaction() as connection:
            connection.execute("UPDATE work_orders SET objective = ?", ("Draft change",))
            with Store(path) as reader:
                agent = AgentTools(reader)
                assert agent.list_work_orders()[0]["objective"] == order.objective
                context = agent.get_work_order_context(order.id)
                assert context["work_order"]["objective"] == order.objective
        assert WorkOrders(writer).get(order.id).objective == "Draft change"


def test_happy_path_to_release(orders):
    id = create(orders).id
    orders.claim(id, "codex")
    artifact = plan()
    submission = orders.submit(id, "codex", artifact)
    assert submission.artifact_digest == canonical_digest(artifact)
    assert submission.number == 1 and submission.passed
    assert orders.get(id).status == "in_review"
    with pytest.raises(WorkOrderError):
        orders.approve(id, " ", 1)
    released = orders.approve(id, "Neal", 1)
    assert released.status == "released" and released.released_submission == 1
    events = orders.history(id)
    assert [e["event"] for e in events] == ["created", "claimed", "submitted", "approved"]
    assert events[-1]["actor"] == "Neal" and events[-1]["submission"] == 1
    assert submission.artifact_digest in events[-1]["note"]


def test_failed_checks_stay_in_progress(orders):
    id = create(orders).id
    orders.claim(id, "codex")
    bad = orders.submit(id, "codex", plan(800))
    assert any("outside [400, 700] nm" in r.detail for r in bad.results if not r.passed)
    assert not bad.passed and bad.number == 1
    assert (orders.get(id).status, orders.get(id).worker) == ("in_progress", "codex")
    with pytest.raises(WorkOrderError):
        orders.approve(id, "Neal", 1)
    good = orders.submit(id, "codex", plan())
    assert good.passed and good.number == 2 and orders.get(id).status == "in_review"
    assert orders.submissions(id) == [bad, good]


def test_submit_requires_claiming_worker_and_in_progress(orders):
    id = create(orders).id
    with pytest.raises(WorkOrderError):
        orders.submit(id, "codex", plan())
    orders.claim(id, "codex")
    with pytest.raises(WorkOrderError):
        orders.submit(id, "claude", plan())
    with pytest.raises(ArtifactError):
        orders.submit(id, "codex", {})
    malformed = plan()
    malformed["steps"] = tuple(malformed["steps"])
    with pytest.raises(ArtifactError):
        orders.submit(id, "codex", malformed)
    assert orders.submissions(id) == []
    assert len(orders.history(id)) == 2
    submission = orders.submit(id, "codex", plan())
    orders.approve(id, "Reviewer", 1)
    with pytest.raises(WorkOrderError):
        orders.submit(id, "codex", plan())
    assert orders.submissions(id) == [submission]


def test_approval_names_reviewed_submission(orders):
    id = create(orders).id
    orders.claim(id, "codex")
    orders.submit(id, "codex", plan())
    orders.reject(id, "Neal", 1, "use 2x dilution")
    orders.claim(id, "claude")
    second = orders.submit(id, "claude", plan(560))
    message = r"submission 1 is not the latest \(latest is 2\)"
    with pytest.raises(WorkOrderError, match=message):
        orders.approve(id, "Neal", 1)
    with pytest.raises(WorkOrderError, match=message):
        orders.reject(id, "Neal", 1, "stale")
    assert orders.get(id).status == "in_review"
    assert orders.approve(id, "Neal", 2).released_submission == 2
    assert second.artifact_digest in orders.history(id)[-1]["note"]


def test_reject_and_handoff(orders):
    id = create(orders).id
    assert orders.latest_rejection(id) is None
    orders.claim(id, "codex")
    with pytest.raises(WorkOrderError):
        orders.approve(id, "Neal", 1)
    orders.submit(id, "codex", plan())
    reopened = orders.reject(id, "Neal", 1, "use 2x dilution")
    assert (reopened.status, reopened.worker) == ("open", None)
    assert orders.latest_rejection(id) == {
        "submission": 1, "by": "Neal", "reason": "use 2x dilution", "artifact": plan(),
    }


def test_checks_use_pinned_lab_revision(orders, store, uvvis_lab_dict, b12_experiment_dict):
    old = create(orders)
    uvvis_lab_dict["instruments"][0]["parameters"][0]["maximum"] = 900
    b12_experiment_dict["goal"] = "Revised experiment"
    assert store.put_lab(lab_from_dict(uvvis_lab_dict)).number == 2
    assert store.put_experiment(experiment_from_dict(b12_experiment_dict)).number == 2
    new = create(orders)
    assert new.lab_revision == new.experiment_revision == 2
    lab, experiment = orders.pinned_context(old.id)
    assert lab.instrument("uvvis-1").parameter("wavelength").maximum == 700
    assert experiment.goal != b12_experiment_dict["goal"]
    for order, passed in [(old, False), (new, True)]:
        orders.claim(order.id, "codex")
        assert orders.submit(order.id, "codex", plan(800)).passed is passed


def test_only_one_claim_wins_across_connections(tmp_path, uvvis_lab_dict, b12_experiment_dict):
    path = tmp_path / "race.db"
    with Store(path) as store:
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        store.put_experiment(experiment_from_dict(b12_experiment_dict))
        orders = WorkOrders(store)
        id = create(orders).id
        barrier = threading.Barrier(2)

        def claim(worker):
            with Store(path) as contender:
                barrier.wait(timeout=5)
                try:
                    return WorkOrders(contender).claim(id, worker)
                except WorkOrderError as exc:
                    return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["codex", "claude"]))
        winners = [r.worker for r in results if isinstance(r, WorkOrder)]
        assert len(winners) == sum(isinstance(r, WorkOrderError) for r in results) == 1
        assert [e["actor"] for e in orders.history(id) if e["event"] == "claimed"] == winners
