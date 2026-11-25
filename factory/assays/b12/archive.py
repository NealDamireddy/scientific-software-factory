"""Integrity-check a previous run for display; never promote it as a fresh release."""
from copy import deepcopy
import difflib
import json
import re

from factory.assays.b12 import b12_build
from factory.assays.b12.b12_verification import validate_receipt
from factory.assays.b12.archive_measurements import record, require, text_field, validate_calibration, validate_measurements
from factory.assays.b12.archive_timing import validate_timing
from factory.assays.b12.archive_verification import validate_verification
from factory.assays.b12.optics import PROFILE, calibration_digest, validate_recipe


def _task_source(task, source):
    require(isinstance(task["id"], str) and re.fullmatch(r"[0-9a-f]{32}", task["id"]), "invalid task id")
    require(task["status"] == "verified", "status must be verified")
    require(task["context"] == PROFILE, "context differs from the pinned B12 profile")
    files = source["files"]
    require(set(files) == set(b12_build.FILES), "source.files must contain all three release artifacts")
    for name, content in files.items():
        require(isinstance(content, str) and 0 < len(content.encode()) <= 65536, f"invalid source file {name}")
    source_bytes = {name: content.encode() for name, content in files.items()}
    if "verification" in task:
        validate_receipt(task, source_bytes, task["release_contract"])
    else:
        require(task["revision"] == b12_build.content_revision(source_bytes), "source revision digest mismatch")
    with record("source.views.json"):
        require(json.loads(files["views.json"]) == task["views"], "views differ from the retained task")
    with record("source.recipe.json"):
        return validate_recipe(json.loads(files["recipe.json"]))


def _evidence_index(bundle, calibration_id, preparation_id):
    references = {
        "Raw measurements retained": "initial.raw, initial.calibration.standards, followup.measurement.raw",
        "Acquisition settings recorded": "initial.raw[].settings, followup.measurement.raw[].settings",
        "Calibration unchanged": calibration_id,
        "Preparation documented": preparation_id,
        "Software and dependencies identified": "sources, environment, direct.worker, followup.worker",
        "Numerical tests passed": "direct.checks, followup.parent_checks, followup.checks",
        "Outstanding scientific review shown": "scientific_review",
    }
    with record("checks"):
        entries = bundle["checks"]
        require(isinstance(entries, list) and len(entries) == len(references), "incomplete evidence checklist")
        for entry in entries:
            name = entry["name"]
            require(name in references and entry["reference"] == references.pop(name),
                    f"invalid or duplicate reference for {name}")
            require(entry["status"] == "recorded", f"{name} status must be recorded")

    for role in ("direct", "followup"):
        with record(f"{role}.worker"):
            worker = bundle[role]["worker"]
            for field in ("method", "model", "cli"):
                text_field(worker, field)
    with record("environment"):
        for key in ("python", "app_dependencies", "dependency_lock"):
            text_field(bundle["environment"], key)
    review = bundle["scientific_review"]
    require(isinstance(review, list) and review and all(isinstance(item, str) and item.strip() for item in review),
            "scientific_review is missing open review evidence")


def validate_archive(bundle):
    """Admit a consistent retained package without executing its source or using private labels."""
    with record("archive"):
        require(bundle["profile"] == "research-reproducibility@1", "unsupported evidence profile")
        direct, child = bundle["direct"], bundle["followup"]
        require(direct["id"] != child["id"] and child["parent_id"] == direct["id"],
                "followup.parent_id must identify the distinct original direct task")
        require(child["parent_revision"] == direct["revision"], "followup.parent_revision mismatch")
        require(set(bundle["sources"]) == {direct["id"], child["id"]}, "sources do not identify both tasks")
        recipes = []
        for role, task in (("direct", direct), ("followup", child)):
            with record(role):
                recipes.append(_task_source(task, bundle["sources"][task["id"]]))
        first_source = bundle["sources"][direct["id"]]
        next_source = bundle["sources"][child["id"]]
        differences = []
        for name in b12_build.FILES:
            differences.extend(difflib.unified_diff(first_source["files"][name].splitlines(True),
                                                    next_source["files"][name].splitlines(True),
                                                    "v1/" + name, "v2/" + name))
        require(first_source["diff"] == "" and next_source["diff"] == "".join(differences),
                "sources.diff differs from the retained source files")

        cal = bundle["initial"]["calibration"]
        with record("initial.calibration"):
            require(calibration_digest(cal) == cal["id"], "frozen calibration digest mismatch")
        validate_calibration(cal)
        validate_measurements(bundle, recipes)
        validate_timing(bundle)
        validate_verification(direct, child)
        _evidence_index(bundle, cal["id"], child["preparation"]["id"])
        json.dumps(bundle, allow_nan=False)
    return deepcopy(bundle)
