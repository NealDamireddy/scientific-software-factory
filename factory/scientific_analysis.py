"""Run the retained artifact on a public measurement projection in the offline sandbox."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from .sandbox import execute


INSTRUMENT_PINS = ("instrument_id", "profile_id", "profile_sha256")
OPTICAL_SETTINGS = ("wavelength_nm", "path_length_mm")
CALIBRATION_FIELDS = ("id", "unit", "blank_id", *INSTRUMENT_PINS, *OPTICAL_SETTINGS)
RECORD_FIELDS = (
    "schema_version", *INSTRUMENT_PINS, *OPTICAL_SETTINGS, "blank_id", "timestamp",
    "dark_counts", "blank_counts", "sample_counts", "simulated", "job_id", "sample_id",
    "replicate", "elapsed_s", "unit", "model_revision",
)


def project_fields(source, fields):
    if not isinstance(source, dict):
        raise ValueError("Expected an input object")
    result = {key: source[key] for key in fields if key in source}
    if any(type(value) not in (str, int, float, bool, type(None)) for value in result.values()):
        raise ValueError("Expected scalar public fields")
    return result


def array(source, key):
    value = source.get(key)
    if not isinstance(value, list):
        raise ValueError(f"Expected {key} array")
    return value


def project_group(group, fields):
    result = project_fields(group, fields)
    result["records"] = []
    for record in array(group, "records"):
        reading = project_fields(record, RECORD_FIELDS)
        if "findings" in record:
            findings = array(record, "findings")
            if any(not isinstance(reason, str) for reason in findings):
                raise ValueError("Expected text measurement findings")
            reading["findings"] = list(findings)
        result["records"].append(reading)
    return result


def public_input(payload, kind):
    if not isinstance(payload, dict) or payload.get("experiment_type") != kind:
        raise ValueError("Experiment type differs from verified release")
    fields = CALIBRATION_FIELDS
    if kind == "time_course":
        fields += ("slope", "intercept", "low", "high")
    calibration = project_fields(payload.get("calibration"), fields)
    if not isinstance(calibration.get("id"), str) or not calibration["id"].strip():
        raise ValueError("Expected calibration identity")
    groups = [project_group(item, ("sample_id",)) for item in array(payload, "groups")]
    for group in groups:
        if not isinstance(group.get("sample_id"), str) or not group["sample_id"].strip():
            raise ValueError("Expected sample identity")
    standards = [project_group(item, ("concentration", "unit")) for item in array(payload, "standards")]
    return dict(experiment_type=kind, calibration=calibration, standards=standards, groups=groups)


def result_identity(kind, group):
    row = {"sample_id": group["sample_id"]}
    if kind == "time_course":
        records = group["records"]
        stamp = records[0].get("timestamp") if records else None
        row["timestamp"] = stamp if isinstance(stamp, str) else None
    return row


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def check_output(output, data):
    if (set(output) != {"calibration_id", "results"} or output["calibration_id"] != data["calibration"]["id"]
            or not isinstance(output["results"], list) or len(output["results"]) != len(data["groups"])):
        raise ValueError("Invalid release result envelope or calibration identity")
    for row, group in zip(output["results"], data["groups"]):
        identity = result_identity(data["experiment_type"], group)
        fields = {*identity, "concentration_mg_l", "replicate_sd_mg_l", "review_reason"}
        if not isinstance(row, dict) or set(row) != fields or any(row[k] != v for k, v in identity.items()):
            raise ValueError("Invalid result fields, sample identity or measurement timestamp")
        mean, sd, reason = row["concentration_mg_l"], row["replicate_sd_mg_l"], row["review_reason"]
        if mean is None:
            if sd is not None or not isinstance(reason, str) or not reason.strip():
                raise ValueError("A withheld estimate requires a review reason and null SD")
        else:
            count = len(group["records"])
            if not finite(mean) or reason is not None or not count:
                raise ValueError("Invalid concentration estimate")
            if count == 1 and sd is not None or count > 1 and (not finite(sd) or sd < 0):
                raise ValueError("Invalid replicate SD")
    return output


def analyze_release(repository, release_id, payload):
    """Return validated results for a verified revision, preserving input group order."""
    manifest, files = repository.load(release_id)
    kind = manifest["experiment_type"]
    data = public_input(payload, kind)
    calibration = data["calibration"]
    recipe = json.loads(files["recipe.json"])
    pins = {key: recipe[key] for key in INSTRUMENT_PINS}
    pins.update({key: recipe["settings"][key] for key in OPTICAL_SETTINGS})
    if "blank_id" in recipe:
        pins["blank_id"] = recipe["blank_id"]
    for field, expected in pins.items():
        value = calibration.get(field)
        if type(value) is not type(expected) or value != expected:
            reason = f"Calibration {field} differs from the verified acquisition recipe"
            rows = [dict(result_identity(kind, group), concentration_mg_l=None, replicate_sd_mg_l=None,
                         review_reason=reason) for group in data["groups"]]
            return {"calibration_id": calibration["id"], "results": rows}
    with TemporaryDirectory() as tmp:
        source = Path(tmp) / "analysis.py"
        source.write_bytes(files["analysis.py"])
        # Negative measurement inputs (including NaN) must reach candidate validation.
        output, _ = execute(source, json.dumps(data).encode())
    return check_output(output, data)
