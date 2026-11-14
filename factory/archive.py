"""Integrity-check a previous run for display; never promote it as a fresh release."""
from copy import deepcopy
import json
import re

from . import b12_build
from .optics import PROFILE, calibration_digest, validate_recipe


def validate_archive(bundle):
    """Check retained identities and content. This does not execute candidate code."""
    try:
        json.dumps(bundle, allow_nan=False)
        if bundle["profile"] != "research-reproducibility@1":
            raise ValueError("Unsupported evidence profile")
        direct, child = bundle["direct"], bundle["followup"]
        if (direct["id"] == child["id"] or child["parent_id"] != direct["id"]
                or child["parent_revision"] != direct["revision"]):
            raise ValueError("Broken source lineage")
        cal = bundle["initial"]["calibration"]
        if calibration_digest(cal) != cal["id"]:
            raise ValueError("Frozen calibration digest mismatch")
        if child["measurement"]["calibration_id"] != cal["id"]:
            raise ValueError("Follow-up calibration mismatch")
        if set(bundle["sources"]) != {direct["id"], child["id"]}:
            raise ValueError("Unexpected archived source tasks")
        for task in (direct, child):
            if not isinstance(task["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", task["id"]):
                raise ValueError("Invalid archived task ID")
            if task["status"] != "verified" or task["context"] != PROFILE:
                raise ValueError("Archive requires completed, pinned tasks")
            if task["result"]["calibration_id"] != cal["id"]:
                raise ValueError("Recorded result calibration mismatch")
            files = bundle["sources"][task["id"]]["files"]
            if set(files) != set(b12_build.FILES) or any(
                not isinstance(text, str) or not 0 < len(text.encode()) <= 65536
                for text in files.values()
            ):
                raise ValueError("Unexpected archive artifacts")
            if b12_build.content_revision({name: text.encode() for name, text in files.items()}) != task["revision"]:
                raise ValueError("Archived source digest mismatch")
            validate_recipe(json.loads(files["recipe.json"]))
        if child["preparation"] != child["measurement"]["input"]["preparation"]:
            raise ValueError("Archived preparation mismatch")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Incomplete previous-run package") from error
    return deepcopy(bundle)
