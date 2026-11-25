"""Review, approve and compile immutable local experiment specifications."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
import re
import sqlite3
from uuid import uuid4

from factory.context import digest
from factory.lab_context.context_repository import ContextRepository, RevisionConflict, canonical_json
from factory.instruments.uvvis_contract import InstrumentError, load_profile, profile_sha256, settings_issues, validate, validate_settings

TYPES = ("concentration", "time_course")
_EDITABLE = {"settings", "sample_ids", "standards", "calibration", "schedule", "experiment_type"}


def contract_outputs(kind):
    metrics = ["calibration_id", "sample_id", "concentration_mg_l", "replicate_sd_mg_l", "review_reason"]
    return metrics + (["timestamp"] if kind == "time_course" else [])


def _header(record):
    header = asdict(record)
    del header["payload"]
    return header


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", value) is not None


def _number(value):
    return type(value) in (float, int) and -float("inf") < value < float("inf")


def _recipe_pin(instrument, profile):
    """Project the saved instrument onto the exact pin the adapter will receive."""
    pin = {"schema_version": 1, **{k: instrument.get(k) for k in
                                  ("instrument_id", "profile_id", "profile_sha256")}}
    validate("pin", pin)
    if pin["profile_id"] != profile["profile_id"]:
        raise InstrumentError("profile_id", "Select the registered virtual UV–Vis profile.")
    if pin["profile_sha256"] != profile_sha256(profile):
        raise InstrumentError("profile_sha256", "Select the registered virtual UV–Vis profile digest.")
    return pin


def _time_course_standards_issue(spec):
    if spec["experiment_type"] == "time_course" and spec["standards"] != []:
        return "Remove the standards to use the frozen time-course calibration."


def _check_samples(spec, errors):
    samples = spec["sample_ids"]
    if (not isinstance(samples, list) or not samples or not all(map(_identifier, samples))
            or len(set(samples)) != len(samples)):
        errors["sample_ids"] = "Select distinct opaque sample identifiers."
        samples = []
    standards = spec["standards"]
    if issue := _time_course_standards_issue(spec):
        errors["standards"] = issue
        return
    if not isinstance(standards, list):
        errors["standards"] = "Supply a list of known standards."
        return
    levels, identifiers = set(), set(samples)
    for item in standards:
        if (not isinstance(item, dict) or set(item) != {"sample_id", "known_concentration"}
                or not _identifier(item["sample_id"]) or item["sample_id"] in identifiers
                or not _number(item["known_concentration"]) or item["known_concentration"] <= 0):
            errors["standards"] = "Use distinct standard IDs, separate from unknowns, with positive known levels."
            return
        levels.add(item["known_concentration"])
        identifiers.add(item["sample_id"])
    if spec["experiment_type"] == "concentration" and len(levels) < 3:
        errors["standards"] = "Provide at least three distinct positive concentrations."
    if len(identifiers) > 100:
        errors["sample_ids"] = "Acquisition supports at most 100 combined samples and standards."


def _calibration_issue(spec, db_path):
    """Resolve the approved reference against the local run service's frozen calibration."""
    ref = spec["calibration"]
    if ref is None and spec["experiment_type"] != "time_course":
        return
    required = {"id", "sha256", "contract", "settings", "unit", "instrument_id", "profile_sha256", "blank_id"}
    if (not isinstance(ref, dict) or set(ref) != required or not _identifier(ref["id"])
            or not _identifier(ref["blank_id"])
            or not isinstance(ref["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", ref["sha256"])):
        return "Supply a frozen calibration identity, digest, blank_id, contract, units and instrument settings."
    settings = spec["settings"] if isinstance(spec["settings"], dict) else {}
    if (ref["contract"] != "absorbance-linear@1" or ref["unit"] != spec["units"].get("concentration")
            or any(ref[k] != spec["instrument"][k] for k in ("instrument_id", "profile_sha256"))
            or ref["settings"] != {k: settings.get(k) for k in ("wavelength_nm", "path_length_mm")}):
        return "Calibration contract, instrument, units or optical settings are incompatible."

    # Only the run service writes run_calibrations. An installation which has
    # never frozen a fit has no table yet.
    with closing(sqlite3.connect(db_path)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_calibrations'").fetchone()
        row = db.execute("SELECT payload FROM run_calibrations WHERE sha256=?", (ref["sha256"],)).fetchone() if exists else None
    if row is None:
        return "Select an existing frozen calibration from this project."
    try:
        record = json.loads(row[0])
        actual_digest = digest(canonical_json(record).encode())
        if not isinstance(record, dict) or actual_digest != ref["sha256"]:
            return "Frozen calibration differs from its pinned digest."
        expected = {
            **{k: ref[k] for k in ("id", "contract", "unit", "blank_id", "instrument_id", "profile_sha256")},
            **ref["settings"], "lab_id": spec["lab"]["lab_id"], "project_id": spec["project"]["project_id"],
            "profile_id": spec["instrument"]["profile_id"],
        }
        if any(record.get(k) != value for k, value in expected.items()):
            return "Frozen calibration differs from the approved reference or project."
        if (not all(_number(record.get(k)) for k in ("slope", "intercept", "low", "high"))
                or record["slope"] <= 0 or record["low"] >= record["high"]):
            return "Frozen calibration has no usable linear fit."
    except (TypeError, ValueError):
        return "Frozen calibration payload is invalid."
    return None


def _check_schedule(spec, errors):
    schedule = spec["schedule"]
    if spec["experiment_type"] != "time_course":
        if schedule is not None:
            errors["schedule"] = "Schedules require a time-course specification."
        return
    if not isinstance(schedule, dict) or set(schedule) != {"interval_s", "point_count"}:
        errors["schedule"] = "Select both interval_s and point_count."
        return
    if not _number(schedule["interval_s"]) or not 1 <= schedule["interval_s"] <= 3600:
        errors["schedule.interval_s"] = "Select an interval from 1 to 3600 seconds."
    if type(schedule["point_count"]) is not int or not 2 <= schedule["point_count"] <= 100:
        errors["schedule.point_count"] = "Select an integer from 2 to 100."


class ExperimentSpecificationService:
    """Owns specification and approval tables in the local application database.

    Call start or edit, inspect unresolved fields and confirm the exact digest shown.
    Subsequent application services accept only that digest and re-read its approval.
    """

    def __init__(self, context_repo: ContextRepository, sqlite_db_path):
        self.context = context_repo
        self.path = sqlite_db_path
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiment_specifications (
                    digest TEXT PRIMARY KEY, specification_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, UNIQUE(specification_id, revision));
                CREATE TABLE IF NOT EXISTS specification_approvals (
                    digest TEXT PRIMARY KEY REFERENCES experiment_specifications(digest),
                    actor TEXT NOT NULL, approved_at TEXT NOT NULL, confirmed_fields TEXT NOT NULL);
            """)

    def start(self, lab_id, project_id, *, project_revision=None, experiment_type="concentration"):
        project = self.context.get("project", lab_id, project_id=project_id, revision=project_revision)
        lab = self.context.get("lab", lab_id, revision=project.lab_revision)
        if lab.sha256 != project.lab_sha256:
            raise ValueError("Pinned project and lab revisions do not match")
        protocol = project.payload
        instrument = next(i for i in lab.payload["instruments"] if i["instrument_id"] == protocol["instrument_id"])
        spec = {
            "specification_id": str(uuid4()), "revision": 1, "lab": _header(lab), "project": _header(project),
            "instrument": instrument, "approved_libraries": lab.payload["approved_libraries"],
            "operating_restrictions": lab.payload["operating_restrictions"],
            **{k: protocol[k] for k in ("protocol_id", "protocol_revision", "analysis_method", "units",
                                        "scientific_objective", "validation_criteria")},
            "experiment_type": experiment_type, "verification_contract": f"{experiment_type}@1",
            "sample_ids": protocol.get("sample_ids", []),
            "standards": protocol.get("standards", []) if experiment_type == "concentration" else [],
            "settings": {"operation": "measure-absorbance", "path_length_mm": 10, "replicates": 3,
                         **protocol.get("measurement_settings", {})},
            "outputs": contract_outputs(experiment_type), "calibration": None, "schedule": None,
        }
        return self._insert(spec)

    def _insert(self, spec):
        payload = canonical_json(spec)
        sha = digest(payload.encode())
        with closing(sqlite3.connect(self.path)) as db, db:
            try:
                db.execute("INSERT INTO experiment_specifications VALUES (?, ?, ?, ?)",
                           (sha, spec["specification_id"], spec["revision"], payload))
            except sqlite3.IntegrityError as exc:
                raise RevisionConflict("Specification changed; reload the current revision.") from exc
        return self.get(sha)

    def get(self, sha):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("""SELECT s.payload, a.actor FROM experiment_specifications s
                                LEFT JOIN specification_approvals a USING (digest) WHERE s.digest=?""",
                             (sha,)).fetchone()
        if row is None:
            raise KeyError("Unknown specification digest")
        payload, actor = row
        if digest(payload.encode()) != sha:
            raise ValueError("Stored specification digest mismatch")
        return {**json.loads(payload), "sha256": sha, "status": "approved" if actor else "draft"}

    def edit(self, sha, **changes):
        if not changes or changes.keys() - _EDITABLE:
            raise ValueError(f"Edit one or more scientific fields from {sorted(_EDITABLE)}.")
        spec = self.get(sha)
        del spec["sha256"], spec["status"]
        kind = changes.get("experiment_type", spec["experiment_type"])
        if kind != spec["experiment_type"]:
            if kind == "time_course":
                changes.setdefault("standards", [])
            elif kind == "concentration":
                changes.setdefault("schedule", None)
        spec.update(changes)
        if "experiment_type" in changes:
            spec["verification_contract"] = f"{spec['experiment_type']}@1"
            spec["outputs"] = contract_outputs(spec["experiment_type"])
        spec["revision"] += 1
        return self._insert(spec)

    @staticmethod
    def confirmation_fields(spec):
        fields = {"experiment_type", "settings", "sample_ids", "units", "outputs", "validation_criteria"}
        fields.update(k for k in ("standards", "calibration", "schedule") if spec[k])
        return sorted(fields)

    def unresolved(self, spec):
        errors = {}
        if spec["experiment_type"] not in TYPES:
            errors["experiment_type"] = "Unsupported experiment type: no verification contract."
        required_units = {"concentration": "mg/L", "wavelength": "nm", "path_length": "mm"}
        for key, unit in required_units.items():
            if spec["units"].get(key) != unit:
                errors[f"units.{key}"] = f"The v1 contract requires {unit}."
        profile = load_profile()
        try:
            _recipe_pin(spec["instrument"], profile)
        except InstrumentError as issue:
            errors[f"instrument.{issue.field}"] = issue.reason
        settings = spec["settings"]
        for issue in settings_issues(settings, profile):
            field = f"settings.{issue.field}" if issue.field != "settings" else "settings"
            errors.setdefault(field, issue.reason)
        _check_samples(spec, errors)
        _check_schedule(spec, errors)
        if issue := _calibration_issue(spec, self.path):
            errors["calibration"] = issue
        return errors

    def approve(self, sha, *, actor, confirmed_fields):
        spec = self.get(sha)
        errors = self.unresolved(spec)
        if not isinstance(actor, str) or not actor.strip():
            errors["actor"] = "Identify the local researcher approving this revision."
        expected = self.confirmation_fields(spec)
        if set(confirmed_fields or ()) != set(expected):
            errors["confirmation"] = f"Explicitly confirm these fields on this revision: {', '.join(expected)}."
        if errors:
            raise ValueError("; ".join(f"{k}: {v}" for k, v in errors.items()))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""INSERT INTO specification_approvals VALUES (?, ?, ?, ?)
                          ON CONFLICT(digest) DO NOTHING""",
                       (sha, actor.strip(), datetime.now(timezone.utc).isoformat(), json.dumps(expected)))
        return self.approved(sha)[1]

    def approved(self, sha):
        spec = self.get(sha)
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("""SELECT actor, approved_at, confirmed_fields
                                FROM specification_approvals WHERE digest=?""", (sha,)).fetchone()
        if row is None:
            raise ValueError("Specification revision requires approval")
        # Older approvals can predate the empty-standards time-course contract check.
        if issue := _time_course_standards_issue(spec):
            raise ValueError(f"standards: {issue}")
        if issue := _calibration_issue(spec, self.path):
            raise ValueError(f"calibration: {issue}")
        return spec, {"actor": row[0], "approved_at": row[1], "confirmed_fields": json.loads(row[2]),
                      "specification_sha256": sha}

    def compile_recipe(self, sha):
        spec, _ = self.approved(sha)
        settings = spec["settings"].copy()
        for key in ("wavelength_nm", "path_length_mm", "replicates"):
            settings[key] = int(settings[key])
        profile = load_profile()
        recipe = {**_recipe_pin(spec["instrument"], profile), "settings": settings}
        validate("blank_request", recipe)
        validate_settings(settings, profile)
        return recipe
