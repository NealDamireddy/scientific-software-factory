from dataclasses import replace
import json

import pytest

from labfactory import tabular_service
from labfactory.analysis_context import choices
from labfactory.agent import AgentTools
from labfactory.context import ContextError, Document, Experiment, Instrument, Lab
from labfactory.store import NotFound
from labfactory.workorders import WorkOrders


def register_stage(store, export, origin):
    instrument = Instrument("stage", "Translation stage", "Encoder S", "2" if export == "millimetres" else "1",
                            (), (), export)
    unused = replace(instrument, id="spare", notes="unused-instrument-private")
    handbook = Document("export", "manual", "Stage export handbook", "Lab handbook §2",
                        "The reading column contains the assigned stage's exported coordinate. Use its recorded units.")
    private = Document("certificate", "note", "Certificate", "Reviewer", "private-certificate")
    store.put_lab(Lab("metrology", "Metrology lab", (instrument, unused), (handbook, private)))
    method = Document("origin", "sop", "Reporting origin", "Stage project §3",
                      f"Report signed displacement as stage position in mm minus the project origin of {origin} mm.")
    store.put_experiment(Experiment("drift", "metrology", "Stage alignment", "Measure signed displacement from "
                                    "the project origin.", ("stage",), (method, private)))


def stage_request(expected):
    return {
        "objective": "Build me an app that reports this stage's displacement from our project origin.",
        "unit": "mm", "range_gate": False, "csv_name": "batch.csv",
        "csv": "sample,role,reading\nprivate-check,control,120\nunknown-a,unknown,92\n",
        "mapping": {"id": "sample", "role": "role", "signal": "reading"},
        "control_expected": expected, "control_tolerance": 0.001,
        "research_context": {"experiment_id": "drift", "lab_document_ids": ["export"],
                             "experiment_document_ids": ["origin"]},
    }


def test_context_is_scoped_pinned_and_reused_on_retry(store):
    register_stage(store, "4 encoder ticks per millimetre", 2)
    req = {**stage_request(28), "request_id": "20910f71-9330-4cdb-8497-17d788c921ed"}
    order = tabular_service.create_order(store, "Reviewer", req)
    register_stage(store, "millimetres", 8)
    assert tabular_service.create_order(store, "Reviewer", req) == order
    author = AgentTools(store)
    ctx = author.get_work_order_context(order["id"])
    evidence = ctx["analysis"]["research_context"]
    assert evidence["lab"]["revision"] == evidence["experiment"]["revision"] == 1
    assert evidence["lab"]["instruments"][0]["notes"] == "4 encoder ticks per millimetre"
    assert "2 mm" in evidence["experiment"]["documents"][0]["text"]
    assert evidence["lab"]["documents"][0]["source"] == "Lab handbook §2"
    assert ctx["analysis"]["protocol"] is None
    with pytest.raises(NotFound):
        tabular_service.original(store, order["id"], "protocol")
    for private in ("private-check", "private-certificate", "unused-instrument-private", "unknown-a"):
        assert private not in json.dumps(ctx)
    author.claim_work_order(order["id"], "Author")
    source = "def analyze(standards, signal, factor):\n    return signal / 4 - 2"
    cases = [{"label": str(x), "standards": [], "signal": x, "factor": 1, "expected": y}
             for x, y in [(4, -1), (20, 3)]]
    sub = author.submit_artifact(order["id"], "Author", {"source": source, "explanation": "Use the encoder scale "
                                 "and project origin.", "tests": cases})
    assert sub["passed"]
    WorkOrders(store).approve(order["id"], "Reviewer", 1)
    receipt = tabular_service.run(store, order["id"], "Reviewer", {"submission": 1})
    assert receipt["results"][0]["value"] == 21
    assert receipt["research_context"]["lab"]["digest"] == evidence["lab"]["digest"]
    assert receipt["research_context"]["experiment"]["revision"] == 1


def test_unknown_context_document_rolls_back(store):
    register_stage(store, "millimetres", 2)
    req = stage_request(118)
    req["research_context"]["experiment_document_ids"] = ["export"]
    with pytest.raises(ContextError, match="Unknown document"):
        tabular_service.create_order(store, "Reviewer", req)
    assert tabular_service.catalog(store)["orders"] == []


def test_archived_readings_can_select_the_acquisition_revisions(store):
    register_stage(store, "4 encoder ticks per millimetre", 2)
    register_stage(store, "millimetres", 8)
    req = stage_request(28)
    req["research_context"].update(lab_revision=1, experiment_revision=1)
    order = tabular_service.create_order(store, "Reviewer", req)
    research = AgentTools(store).get_work_order_context(order["id"])["analysis"]["research_context"]
    assert research["lab"]["instruments"][0]["firmware"] == "1"
    assert "2 mm" in research["experiment"]["documents"][0]["text"]
    current, = choices(store)["experiments"]
    assert current["id"] == "drift" and current["revision"] == current["lab"]["revision"] == 2
    assert "private-certificate" not in json.dumps(current)
