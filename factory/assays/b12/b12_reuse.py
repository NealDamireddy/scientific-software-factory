"""Select checked source from original, live B12 releases in the presenter store."""
import json
from pathlib import Path
import re

from factory.assays.b12 import b12_build
from factory.assays.b12.b12_verification import validate_receipt, verification_receipt
from factory.context import read_json
from factory.assays.b12.optics import PROFILE, RECIPE, matches_expected, validate_recipe, verification_cases
from factory.software.release_planner import compatibility_reasons


_PREPARED_METRICS = ("parent_id", "preparation_id", "factor", "diluted_mg_l")


def release_contract(prepared):
    """Versioned B12 source pins independent of a vial, dilution or particular fit."""
    return {
        **PROFILE,
        "capabilities": ["direct", "prepared"] if prepared else ["direct"],
        "units": {"detector": "counts", "concentration": "mg/L", "volume": "mL"},
        "settings": {**RECIPE, "path_length_mm": 10},
        "input_schema": "b12-assay-input@1",
        "output_schema": "b12-assay-result@1",
        "approved_libraries": ["json", "math", "statistics", "sys"],
        "calibration_contract": "b12-optical@1",
    }


def _read_artifacts(folder, task):
    files = {}
    for name in b12_build.FILES:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid release artifact: {name}")
        files[name] = path.read_bytes()
    if b12_build.content_revision(files) != task.get("revision"):
        raise ValueError("Released source digest mismatch")
    validate_recipe(json.loads(files["recipe.json"]))
    return files


def _checked_results(report, prepared):
    """Compare persisted verdicts and outputs against the actual verifier's contract."""
    expected = {name: output for name, _, output in verification_cases(prepared)}
    try:
        json.dumps(report, allow_nan=False)
    except ValueError as error:
        raise ValueError("Nonfinite optical verification contract evidence") from error
    if not isinstance(report, list) or len(report) != len(expected):
        raise ValueError("Incomplete optical verification contract")
    results = {}
    for check in report:
        name = check.get("name")
        if name not in expected or name in results or check.get("expected") != expected[name]:
            raise ValueError("Recorded optical verification contract differs from the pinned cases")
        actual = check.get("actual")
        if not isinstance(actual, dict) or not actual:
            raise ValueError("Missing optical verification contract output")
        passed = matches_expected(actual, expected[name])
        if check.get("pass") is not passed:
            raise ValueError("Recorded optical verification contract disagrees with the output")
        results[name] = passed
    return results


def validate_parent_checks(report):
    """Require a healthy direct release that explicitly declined both valid dilutions."""
    results = _checked_results(report, prepared=True)
    for check in report:
        name = check["name"]
        if name in ("prepared-2x", "prepared-4x"):
            expected = check["expected"]
            decline = {"sample_id": expected["sample_id"], "calibration_id": expected["calibration_id"],
                       "status": "review", "concentration_mg_l": None}
            if (not matches_expected(check["actual"], decline)
                    or check["actual"].get("diluted_mg_l") is not None):
                raise ValueError(f"Parent verification did not safely decline {name}")
        elif not results[name]:
            raise ValueError(f"Parent verification failed {name}")


def _validate_verification(task, prepared):
    worker = task.get("worker")
    if (not isinstance(worker, dict) or not isinstance(worker.get("method"), str)
            or not worker["method"].strip()):
        raise ValueError("Missing original worker receipt")
    if worker["method"] == "codex exec" and not all(
            isinstance(worker.get(field), str) and worker[field].strip() for field in ("model", "cli")):
        raise ValueError("Missing original worker CLI or model provenance")
    if not all(_checked_results(task.get("checks"), prepared).values()):
        raise ValueError("Failed optical verification contract")
    if prepared:
        validate_parent_checks(task.get("parent_checks"))
        if (not re.fullmatch(r"[a-f0-9]{64}", task.get("parent_revision", ""))
                or task["parent_revision"] == task["revision"]):
            raise ValueError("Incomplete original preparation verification provenance")


class _NotAnOriginal(ValueError):
    """Pending, failed, archived and reused tasks are outside the source catalog."""


def _load_task(folder):
    path = folder / "task.json"
    if folder.is_symlink() or path.is_symlink():
        raise ValueError("Invalid original release path")
    task = read_json(path)
    if task.get("id") != folder.name or not re.fullmatch(r"[a-f0-9]{32}", folder.name):
        raise ValueError("Invalid original release identity")
    return task


def _is_original(task):
    return (task.get("status") == "verified" and task.get("mode") == "fresh generation"
            and not task.get("origin_task_id") and not task.get("archived"))


def read_release(folder, prepared=False):
    """Load a specific original and validate its eligibility for the requested capability."""
    folder = Path(folder)
    try:
        task = _load_task(folder)
        if not _is_original(task):
            raise _NotAnOriginal("Original live verified release required")
        return _candidate(folder, task, release_contract(prepared))
    except (KeyError, TypeError, AttributeError, ArithmeticError, OSError) as error:
        raise ValueError(f"Invalid release record: {error}") from error


def _parent_folder(store, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid parent release identity")
    folder = store / identifier
    if not folder.is_dir():
        raise ValueError("Original parent release is missing")
    return folder


def _validate_parent(folder, child):
    """Resolve the direct run and, when it reused source, its original direct release."""
    parent_folder = _parent_folder(folder.parent, child["parent_id"])
    parent = _load_task(parent_folder)
    if parent.get("parent_id") or parent.get("status") != "verified" or parent.get("archived"):
        raise ValueError("Prepared release requires a verified live direct parent")
    if parent.get("revision") != child["parent_revision"]:
        raise ValueError("Prepared release parent revision differs from the identified parent")

    if child.get("approval", {}).get("origin") != parent["id"]:
        raise ValueError("Original preparation approval identifies a different parent")
    origin_folder = parent_folder
    origin = parent
    if not _is_original(parent):
        if parent.get("mode") != "verified source reuse":
            raise ValueError("Invalid parent release creation mode")
        origin_folder = _parent_folder(folder.parent, parent.get("origin_task_id"))
        origin = _load_task(origin_folder)
        if origin.get("parent_id") or not _is_original(origin):
            raise ValueError("Parent reuse must resolve to an original direct release")
    # A prepared original can only have been generated from code lacking preparation.
    # Requiring a direct original here also prevents recursive parent/origin chains.
    source = _candidate(origin_folder, origin, release_contract(False))
    if origin_folder != parent_folder:
        files = _read_artifacts(parent_folder, parent)
        if (source["files"] != files or parent.get("context") != PROFILE
                or parent.get("release_contract") != source["release_contract"]
                or any(parent.get(key) != source[key] for key in ("worker", "checks", "verification"))):
            raise ValueError("Parent reuse evidence differs from its original direct release")
    expected = verification_receipt(source["revision"], child["parent_checks"],
                                    source["worker"], release_contract(True))
    if child.get("parent_verification") != expected:
        raise ValueError("Parent verification receipt does not bind the identified parent source and checks")
    return {"parent_origin_task_id": source["id"], "parent_worker": source["worker"]}


def _candidate(folder, task, requested):
    if not isinstance(task.get("created"), str):
        raise ValueError("Missing original release timestamp")
    if task.get("context") != PROFILE:
        reasons = compatibility_reasons(task.get("context") or {}, PROFILE)
        raise ValueError(", ".join(reasons) or "Incompatible B12 context")

    files = _read_artifacts(folder, task)
    prepared = bool(task.get("parent_id"))
    views = json.loads(files["views.json"])
    metrics = (*b12_build.METRICS, *_PREPARED_METRICS) if prepared else b12_build.METRICS
    if views != task.get("views") or sorted(views["metrics"]) != sorted(metrics):
        raise ValueError("Released view does not match the verified capabilities")
    _validate_verification(task, prepared)

    original = release_contract(prepared)
    contract = task.get("release_contract", original)
    declared = compatibility_reasons(contract, original)
    if contract["capabilities"] != original["capabilities"]:
        declared.append("Incompatible declared B12 capabilities")
    if declared:
        raise ValueError(", ".join(declared))

    verification = validate_receipt(task, files, contract)
    lineage = _validate_parent(folder, task) if prepared else {}
    reasons = compatibility_reasons(contract, requested)
    if reasons:
        raise ValueError(", ".join(reasons))
    return {
        **lineage, "verification": verification, "parent_verification": task.get("parent_verification"),
        "created": task["created"], "id": task["id"], "revision": task["revision"], "files": files,
        "worker": task["worker"], "checks": task["checks"],
        "parent_checks": task.get("parent_checks"), "parent_revision": task.get("parent_revision"),
        "release_contract": contract,
    }


def select_release(store, prepared):
    """Prefer the latest original with the requested capability, then a superset.

    Return a checked byte snapshot and a mapping from rejected task IDs to reasons.
    Never scan the bundled previous run or follow a reused run's source pointers.
    """
    requested_capabilities = release_contract(prepared)["capabilities"]
    rejections = {}
    chosen = None
    best = None
    for path in Path(store).glob("*/task.json"):
        folder = path.parent
        try:
            candidate = read_release(folder, prepared)
            exact = candidate["release_contract"]["capabilities"] == requested_capabilities
            priority = (exact, candidate["created"], candidate["id"])
            if best is None or priority > best:
                chosen, best = candidate, priority
        except _NotAnOriginal:
            continue
        except ValueError as error:
            rejections[folder.name] = [str(error)]
    return chosen, rejections
