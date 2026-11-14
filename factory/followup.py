"""Run and replay trusted optical measurements against content-identified app releases."""
from datetime import datetime, timezone
import json
import math
import secrets
from statistics import mean

from . import b12_build
from .context import read_json
from .optics import PROFILE, RECIPE, acquire, assess, calibration_digest, validate_preparation, validate_recipe
from .sandbox import execute


def _released_recipe(folder, task):
    if folder.name != task.get("id") or task.get("status") != "verified":
        raise ValueError("A verified app task is required")
    if b12_build.revision(folder) != task.get("revision"):
        raise ValueError("Released source digest mismatch")
    return validate_recipe(read_json(folder / "recipe.json"))


def _check_calibration(calibration, expected_id):
    if not expected_id or calibration.get("id") != expected_id or calibration_digest(calibration) != expected_id:
        raise ValueError("Frozen calibration digest mismatch")


def _payload(raw, calibration, sample_id, preparation, recipe):
    for index, record in enumerate(raw, start=1):
        if (record.get("sample_id") != sample_id or record.get("replicate") != index
                or record.get("instrument_profile") != calibration["instrument_profile"]
                or record.get("source") != "simulated instrument" or record.get("units") != "counts"):
            raise ValueError("Raw readings do not match the pinned sample or instrument")
        settings = record.get("settings", {})
        if any(settings.get(key) != value for key, value in recipe.items()) or settings.get("path_length_mm") != 10:
            raise ValueError("Raw acquisition settings differ from the released recipe")
    finding = assess(raw, calibration)
    payload = dict(sample_id=sample_id, preparation=preparation, absorbances=finding["absorbances"],
                   calibration={key: calibration[key] for key in ("id", "low", "high", "slope", "intercept")})
    return payload, finding


def _checked_execution(folder, payload, finding):
    cal = payload["calibration"]
    sample = payload["sample_id"]
    preparation = payload["preparation"]
    factor = validate_preparation(sample, preparation) if preparation is not None else 1
    result, sandbox = execute(folder / "analysis.py", json.dumps(payload, allow_nan=False).encode())
    if result.get("sample_id") != sample or result.get("calibration_id") != cal["id"]:
        raise ValueError("Assay sample or calibration identifier mismatch")
    if not finding["in_range"]:
        if result.get("status") != "review" or "concentration_mg_l" not in result or result["concentration_mg_l"] is not None:
            raise ValueError("Out-of-range assay must withhold concentration")
        return result, sandbox

    if result.get("status") != "ok":
        raise ValueError("In-range assay requires an accepted concentration")
    diluted = (mean(payload["absorbances"]) - cal["intercept"]) / cal["slope"]
    values = {"concentration_mg_l": diluted * factor}
    if preparation is not None:
        if result.get("parent_id") != preparation["parent_id"] or result.get("preparation_id") != preparation["id"]:
            raise ValueError("Assay result has invalid preparation lineage")
        values.update(diluted_mg_l=diluted, factor=factor)
    for key, reference in values.items():
        actual = result.get(key)
        if type(actual) not in (float, int) or not math.isclose(actual, reference, rel_tol=1e-7, abs_tol=1e-7):
            raise ValueError(f"{key} disagrees with the independent calibration and preparation")
    return result, sandbox


def run_followup(original_folder, child_folder, parent_task, child_task):
    parent_recipe = _released_recipe(original_folder, parent_task)
    child_recipe = _released_recipe(child_folder, child_task)
    if parent_recipe != child_recipe or child_task.get("parent_revision") != parent_task["revision"]:
        raise ValueError("Follow-up does not match original app or instrument")
    approval = child_task.get("approval") or {}
    if (child_task.get("parent_id") != parent_task["id"] or approval.get("origin") != parent_task["id"]
            or approval.get("protocol") != PROFILE["protocol"] or not approval.get("approved_at")):
        raise ValueError("Approved follow-up of this original run is required")
    preparation = child_task.get("preparation") or {}
    child_id = preparation.get("sample_id")
    factor = validate_preparation(child_id, preparation)
    approved_factor = approval.get("factor")
    if type(approved_factor) not in (int, float) or not math.isclose(factor, approved_factor):
        raise ValueError("Recorded volumes differ from the approved dilution")

    original = read_json(original_folder / "acquisition.json")
    calibration = original["calibration"]
    parent_result = parent_task["result"]
    _check_calibration(calibration, parent_result["calibration_id"])
    parent_id = preparation["parent_id"]
    if (parent_result.get("sample_id") != parent_id or original["input"]["sample_id"] != parent_id
            or parent_result.get("status") != "review" or parent_result.get("concentration_mg_l") is not None):
        raise ValueError("Preparation parent does not match the original above-range run")
    _, initial_finding = _payload(original["raw"], calibration, parent_id, None, parent_recipe)
    if not initial_finding["above_range"]:
        raise ValueError("Original measurement does not support the approved follow-up")

    original_label = read_json(original_folder / "private.json")["prepared_mg_l"]
    raw = acquire(child_recipe, original_label / factor, secrets.randbits(63), sample_id=child_id)
    payload, finding = _payload(raw, calibration, child_id, preparation, child_recipe)
    result, sandbox = _checked_execution(child_folder, payload, finding)
    return {
        "raw": raw, "calibration_id": calibration["id"], "input": payload,
        "result": result, "finding": finding, "sandbox": sandbox,
        "time": datetime.now(timezone.utc).isoformat(), "revision": child_task["revision"],
    }


def replay_acquisition(folder, measurement, calibration):
    """Recalculate from the recorded detector counts, frozen fit and released recipe."""
    task = read_json(folder / "task.json")
    recipe = _released_recipe(folder, task)
    if measurement.get("revision", task["revision"]) != task["revision"]:
        raise ValueError("Measurement belongs to another source revision")
    data = measurement["input"]
    cal_id = data["calibration"]["id"]
    _check_calibration(calibration, cal_id)
    if measurement.get("calibration_id", cal_id) != cal_id:
        raise ValueError("Measurement calibration identifier mismatch")
    preparation = data["preparation"]
    if preparation != task.get("preparation"):
        raise ValueError("Replay preparation differs from the recorded task")
    payload, finding = _payload(measurement["raw"], calibration, data["sample_id"], preparation, recipe)
    return _checked_execution(folder, payload, finding)[0]
