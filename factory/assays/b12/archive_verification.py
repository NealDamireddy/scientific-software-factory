"""Public verification evidence required by the retained optical-checks contracts."""
import hashlib
import json
import math
import re
import sys

from factory.assays.b12.b12_verification import verification_receipt
from factory.assays.b12.optics import PROFILE, RECIPE, VALID_PREPARED_CASES, verification_cases


def _result(sample, concentration=None, calibration_id="ref-cal-v1", **lineage):
    return {
        "sample_id": sample,
        "calibration_id": calibration_id,
        "status": "review" if concentration is None else "ok",
        "concentration_mg_l": concentration,
        **lineage,
    }


# These are the published expectations for optical-checks@1. A future suite
# can change without changing the meaning of records produced with this one.
# @1 is retained only to validate archives; its single calibration had an
# intercept of exactly twice its slope, so @1 cannot tell some wrong formulas
# from the right one. New releases are verified with @2.
_DIRECT = {
    "direct-mean-and-intercept": _result("direct-mean-and-intercept", 12),
    "direct-calibrated-boundaries": _result("direct-calibrated-boundaries", 15),
    "above-calibration": _result("above-calibration"),
    "below-calibration": _result("below-calibration"),
    "one-replicate-outside": _result("one-replicate-outside"),
}
_PREPARED = {
    "prepared-2x": _result("D2", 18, diluted_mg_l=9, factor=2, parent_id="R2", preparation_id="P2"),
    "prepared-4x": _result("D4", 28, diluted_mg_l=7, factor=4, parent_id="R4", preparation_id="P4"),
}
_FULL = {
    **_DIRECT, **_PREPARED,
    **{f"prepared-{case}": _result("D2") for case in (
        "one-outside", "missing-parent", "self-parent", "missing-preparation-id",
        "invalid-unit", "zero-sample", "invalid-final-volume", "equal-volumes", "invalid-volume-type",
    )},
}


def _validate_observation(path, actual, reference, version="optical-checks@1"):
    if not isinstance(actual, dict):
        raise ValueError(f"{path} requires an observed result")
    for field, required in reference.items():
        if field not in actual:
            raise ValueError(f"{path}.{field} missing")
        value = actual[field]
        if type(required) in (int, float):
            # The producer compares observed values with 1e-7 tolerances.
            # Bound the JSON number before conversion to double in isclose.
            matches = (type(value) in (int, float) and abs(value) <= sys.float_info.max
                       and math.isclose(value, required, rel_tol=1e-7, abs_tol=1e-7))
        else:
            matches = value == required
        if not matches:
            raise ValueError(f"{path}.{field} disagrees with {version}")


def _validate_suite(path, records, contract, *, direct_source=False, declines=frozenset(_PREPARED), version="optical-checks@1"):
    if not isinstance(records, list) or not records:
        raise ValueError(f"{path} requires the completed {version} suite")
    seen = set()
    for index, record in enumerate(records):
        name = record.get("name") if isinstance(record, dict) else None
        if not isinstance(name, str) or name not in contract:
            raise ValueError(f"{path}[{index}].name is not an {version} case")
        case = f"{path}[{name}]"
        if name in seen:
            raise ValueError(f"{case} duplicated")
        seen.add(name)
        reference = contract[name]
        if record.get("expected") != reference:
            raise ValueError(f"{case}.expected disagrees with {version}")

        # The v1 source declines valid prepared samples when tested against
        # v2's extended contract. Only these two declines are expected failures.
        decline = direct_source and name in declines
        required_pass = not decline
        if record.get("pass") is not required_pass:
            raise ValueError(f"{case}.pass disagrees with the required verdict")
        observed = _result(reference["sample_id"], calibration_id=reference["calibration_id"]) if decline else reference
        _validate_observation(f"{case}.actual", record.get("actual"), observed, version)

    missing = contract.keys() - seen
    if missing:
        raise ValueError(f"{path} missing required checks: {', '.join(sorted(missing))}")


def _expected(prepared):
    return {name: expected for name, _, expected in verification_cases(prepared)}


# Pin the published @2 expectations by digest, so changing the live suite
# without a new profile version cannot silently change how @2 archives validate.
_V2_DIGEST = "cfc08bb6e8b4cbcddd249e51066b758af882df8093eefcd7025fb5ffcfcdedb9"
if hashlib.sha256(json.dumps(_expected(True), sort_keys=True).encode()).hexdigest() != _V2_DIGEST:
    raise RuntimeError("optical-checks@2 cases changed; publish them under a new verification profile")

_LEGACY_PROFILE = {**PROFILE, "verification_profile": "optical-checks@1"}
# verification_profile -> (context, direct suite, full suite, valid prepared cases)
SUITES = {
    "optical-checks@1": (_LEGACY_PROFILE, _DIRECT, _FULL, frozenset(_PREPARED)),
    "optical-checks@2": (PROFILE, _expected(False), _expected(True), frozenset(VALID_PREPARED_CASES)),
}


def _contract_pins(profile):
    return {
        **profile,
        "units": {"detector": "counts", "concentration": "mg/L", "volume": "mL"},
        "settings": {**RECIPE, "path_length_mm": 10},
        "input_schema": "b12-assay-input@1",
        "output_schema": "b12-assay-result@1",
        "approved_libraries": ["json", "math", "statistics", "sys"],
        "calibration_contract": profile["protocol"],
    }


def suite_for(context):
    """Return the retained suite for an archived task context, or raise."""
    for suite in SUITES.values():
        if context == suite[0]:
            return suite
    raise ValueError("context differs from every pinned B12 profile")


def _check(path, records, suite, full, *, direct_source=False):
    context, direct, complete, declines = suite
    _validate_suite(path, records, complete if full else direct, direct_source=direct_source,
                    declines=declines, version=context["verification_profile"])


def _release_provenance(role, task, run_ids, suite):
    """Return whether the retained source supports prepared samples."""
    mode = task.get("mode")
    if mode not in ("fresh generation", "verified source reuse"):
        raise ValueError(f"{role}.mode must identify the retained source")
    reused = mode == "verified source reuse"
    if reused:
        origin = task.get("origin_task_id")
        if not isinstance(origin, str) or not re.fullmatch("[0-9a-f]{32}", origin) or origin in run_ids:
            raise ValueError(f"{role}.origin_task_id must identify a distinct original release")
    elif "origin_task_id" in task:
        raise ValueError(f"{role}.origin_task_id contradicts fresh generation")

    prepared = role == "followup"
    if reused or "release_contract" in task:
        contract = task.get("release_contract")
        if not isinstance(contract, dict):
            raise ValueError(f"{role}.release_contract missing")
        for key, value in _contract_pins(suite[0]).items():
            if contract.get(key) != value:
                raise ValueError(f"{role}.release_contract.{key} disagrees with the B12 release contract")
        capabilities = contract.get("capabilities")
        if capabilities not in (["direct"], ["direct", "prepared"]):
            raise ValueError(f"{role}.release_contract.capabilities invalid")
        if role == "followup" and capabilities == ["direct"]:
            raise ValueError("followup.release_contract.capabilities requires prepared support")
        if role == "direct" and not reused and capabilities != ["direct"]:
            raise ValueError("direct.release_contract.capabilities contradicts fresh direct generation")
        prepared = "prepared" in capabilities

    if reused and prepared:
        parent = task.get("origin_parent_revision")
        if (not isinstance(parent, str) or not re.fullmatch("[0-9a-f]{64}", parent)
                or parent == task["revision"]):
            raise ValueError(f"{role}.origin_parent_revision must identify the original direct-only source")
        _check(f"{role}.origin_parent_checks", task.get("origin_parent_checks"), suite, True, direct_source=True)
    elif "origin_parent_revision" in task or "origin_parent_checks" in task:
        raise ValueError(f"{role}.origin_parent_revision and origin_parent_checks require prepared source reuse")
    return prepared


def validate_verification(direct, child):
    """Validate the suites associated with the current runs and any retained source origins."""
    run_ids = {direct["id"], child["id"]}
    suite = suite_for(direct.get("context"))
    if child.get("context") != direct.get("context"):
        raise ValueError("followup.context differs from direct.context")
    prepared_parent = _release_provenance("direct", direct, run_ids, suite)
    _release_provenance("followup", child, run_ids, suite)
    # Older optical-checks@1 bundles predate receipts. If the producer supplies
    # them, require the whole chain for each claimed release.
    if any(field in task for task in (direct, child) for field in
           ("verification", "parent_verification", "origin_parent_verification", "origin_parent_worker",
            "origin_parent_task_id")):
        for role, task in (("direct", direct), ("followup", child)):
            if "verification" not in task:
                raise ValueError(f"{role}.verification missing from revision-bound archive")
            if "origin_parent_revision" in task:
                origin_id = task.get("origin_parent_task_id")
                if not isinstance(origin_id, str) or not re.fullmatch("[0-9a-f]{32}", origin_id):
                    raise ValueError(f"{role}.origin_parent_task_id invalid")
                receipt = verification_receipt(task["origin_parent_revision"], task["origin_parent_checks"],
                                               task["origin_parent_worker"], task["release_contract"])
                if task.get("origin_parent_verification") != receipt:
                    raise ValueError(f"{role}.origin_parent_verification differs from retained original evidence")
            elif any(field in task for field in ("origin_parent_verification", "origin_parent_worker",
                                                  "origin_parent_task_id")):
                raise ValueError(f"{role}.origin_parent_verification requires an original prepared release")
        parent_receipt = verification_receipt(direct["revision"], child["parent_checks"], direct["worker"],
                                              child["release_contract"])
        if child.get("parent_verification") != parent_receipt:
            raise ValueError("followup.parent_verification differs from experimental parent evidence")
        if "parent_verification" in direct:
            raise ValueError("direct.parent_verification requires an experimental parent")
        if child.get("origin_parent_task_id") == direct.get("origin_task_id", direct["id"]):
            if (child["origin_parent_revision"] != direct["revision"]
                    or child["origin_parent_worker"] != direct["worker"]):
                raise ValueError("followup.origin_parent_task_id conflicts with the retained direct source")
    _check("direct.checks", direct.get("checks"), suite, prepared_parent)
    _check("followup.parent_checks", child.get("parent_checks"), suite, True, direct_source=not prepared_parent)
    _check("followup.checks", child.get("checks"), suite, True)

    parent_cases = {case["name"]: case for case in child["parent_checks"]}
    for case in direct["checks"]:
        if case != parent_cases[case["name"]]:
            raise ValueError(f"followup.parent_checks[{case['name']}] differs from direct.checks for the same source")

    if prepared_parent:
        if child["mode"] != "verified source reuse":
            raise ValueError("followup.mode contradicts the existing prepared capability")
        if direct["origin_parent_revision"] == child["revision"]:
            raise ValueError("direct.origin_parent_revision refers to prepared follow-up source")
        if (direct["origin_parent_revision"] == child["origin_parent_revision"]
                and direct["origin_parent_checks"] != child["origin_parent_checks"]):
            raise ValueError("followup.origin_parent_checks differ for the same original direct-only source")
    if child.get("origin_parent_revision") == direct["revision"]:
        if child["origin_parent_checks"] != child["parent_checks"]:
            raise ValueError("followup.origin_parent_checks differ from parent_checks for the same source")

    if direct["revision"] == child["revision"]:
        if not prepared_parent or child["mode"] != "verified source reuse":
            raise ValueError("followup.revision equals direct.revision without prepared source reuse")
        for field in ("origin_task_id", "worker", "checks", "release_contract", "origin_parent_revision",
                      "origin_parent_checks"):
            if direct[field] != child[field]:
                raise ValueError(f"followup.{field} disagrees with the reused direct source provenance")
    elif direct.get("origin_task_id") and direct["origin_task_id"] == child.get("origin_task_id"):
        raise ValueError("followup.origin_task_id identifies two different source revisions")
