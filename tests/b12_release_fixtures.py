"""Install current-format test records using the known, reviewed B12 fixture bytes."""
from copy import deepcopy

from factory.assays.b12.b12_build import content_revision
from factory.assays.b12.b12_reuse import release_contract
from factory.assays.b12.b12_verification import verification_receipt


def verified_task(bundle, kind):
    task = deepcopy(bundle[kind])
    files = bundle["sources"][task["id"]]["files"]
    revision = content_revision({name: value.encode() for name, value in files.items()})
    assert revision == task["revision"]
    contract = release_contract(prepared=kind == "followup")
    task["release_contract"] = contract
    task["verification"] = verification_receipt(revision, task["checks"], task["worker"], contract)
    if kind == "followup":
        parent = bundle["direct"]
        assert parent["revision"] == task["parent_revision"]
        task["parent_verification"] = verification_receipt(
            parent["revision"], task["parent_checks"], parent["worker"], contract)
    return task
