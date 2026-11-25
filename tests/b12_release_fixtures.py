"""Install current-format test records using the known, reviewed B12 fixture bytes."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import tempfile

from factory.assays.b12.b12_build import content_revision
from factory.assays.b12.b12_reuse import release_contract
from factory.assays.b12.b12_verification import verification_receipt
from factory.assays.b12.optics import PROFILE, verify_candidate


@lru_cache(maxsize=None)
def _current_checks(source, prepared):
    """Re-verify archived bytes under the current verification profile."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "analysis.py"
        path.write_text(source)
        return json.dumps(verify_candidate(path, prepared=prepared))


def current_checks(source, prepared):
    return json.loads(_current_checks(source, prepared))


def verified_task(bundle, kind):
    task = deepcopy(bundle[kind])
    files = bundle["sources"][task["id"]]["files"]
    revision = content_revision({name: value.encode() for name, value in files.items()})
    assert revision == task["revision"]
    # The public archive was verified under an earlier profile. A live release
    # must carry evidence from the current suite, so verify the same bytes again.
    task["context"] = dict(PROFILE)
    task["checks"] = current_checks(files["analysis.py"], kind == "followup")
    contract = release_contract(prepared=kind == "followup")
    task["release_contract"] = contract
    task["verification"] = verification_receipt(revision, task["checks"], task["worker"], contract)
    if kind == "followup":
        parent = bundle["direct"]
        assert parent["revision"] == task["parent_revision"]
        parent_source = bundle["sources"][parent["id"]]["files"]["analysis.py"]
        task["parent_checks"] = current_checks(parent_source, True)
        task["parent_verification"] = verification_receipt(
            parent["revision"], task["parent_checks"], parent["worker"], contract)
    return task
