"""Resolve a work order into one lab, one project and its offline fixture."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_order(order):
    validator = Draft202012Validator(read_json(ROOT / "registry/work-order.schema.json"))
    errors = sorted(validator.iter_errors(order), key=lambda error: str(error.path))
    if errors:
        raise ValueError("Invalid Work Order: " + errors[0].message)


def resolve(order):
    validate_order(order)
    lab = read_json(ROOT / "registry/lab.json")
    if order["lab"] != lab["id"] or order["project"] not in lab["projects"]:
        raise ValueError("Unknown laboratory or project membership")
    project = read_json(ROOT / "registry/projects" / (order["project"] + ".json"))
    instrument = read_json(ROOT / "registry/instrument.json")
    if project["lab"] != lab["id"] or instrument["id"] != lab["instrument"] or order["instrument"] != lab["instrument"]:
        raise ValueError("Instrument or project does not belong to this lab")
    if order["input"]["dataset"] != project["dataset"]:
        raise ValueError("Dataset does not belong to the selected project")
    return {"lab": lab, "instrument": instrument, "project": project,
            "standards": read_json(ROOT / "registry/standards.json")}


def check(name, status, detail, category):
    return {"name": name, "status": status, "detail": detail, "category": category}


def preflight(order, context, meta, data):
    project, instrument = context["project"], context["instrument"]
    checks = []
    operations = dict.fromkeys(["read-export", project["operation"], *order["operations"]])
    for op in operations:
        cap = instrument["capabilities"].get(op, {"status": "unknown", "reason": "No registered evidence."})
        status = {"supported": "pass", "unsupported": "fail", "unknown": "unknown"}[cap["status"]]
        checks.append(check(op, status, cap["reason"], "simulated instrument"))
    required = instrument["metadata"]
    missing = [field for field in required if meta.get(field) in (None, "")]
    frequency = meta.get("frequency_GHz")
    valid_meta = (not missing and meta["instrument"] == instrument["id"] and meta["synthetic"] is True
                  and isinstance(meta["sample_id"], str) and bool(meta["sample_id"].strip())
                  and meta["acquisition_mode"] == "simulated CW" and type(frequency) in (float, int)
                  and math.isfinite(frequency) and frequency > 0)
    checks.append(check("metadata", "pass" if valid_meta else "fail",
                        "Acquisition metadata matches the registered simulator." if valid_meta else
                        "Missing or invalid acquisition metadata: " + ", ".join(missing or ["inspect metadata.json"]), "data"))
    units_match = project["units"] == meta.get("units") == order["input"]["units"]
    checks.append(check("units", "pass" if units_match else "fail",
                        f"Required {project['units']}. Order declares {order['input']['units']}. Metadata declares {meta.get('units')}.", "data"))
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8")), strict=True)
        if next(reader, []) != project["columns"]:
            raise ValueError("Unexpected CSV header")
        rows = [list(map(float, row)) for row in reader]
        if len(rows) < 3 or any(len(row) != 2 or not all(map(math.isfinite, row)) for row in rows):
            raise ValueError("Expected at least three finite numeric pairs")
        if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
            raise ValueError("Grid must strictly increase")
        if project["id"] == "curie" and rows[0][0] <= 0:
            raise ValueError("Absolute temperature must be positive")
        if project["id"] == "linewidth" and len({row[1] for row in rows}) < 3:
            raise ValueError("Derivative trace has insufficient variation")
        checks.append(check("schema", "pass", f"{len(rows)} validated numeric pairs.", "data"))
    except (ValueError, csv.Error) as exc:
        checks.append(check("schema", "fail", str(exc), "data"))
    compatible = order["parameters"] == project["parameters"]
    checks.append(check("parameters", "pass" if compatible else "unknown",
                        "Registered processing configuration." if compatible else "No reference suite for these parameters.", "engineering"))
    matches = digest(data) == project["reference_input_sha256"]
    checks.append(check("fixture identity", "pass" if matches else "fail",
                        "Input matches the registered reference digest." if matches else "Reference input changed.", "reproducibility"))
    return checks
