"""Submit one approved measurement batch and retain its application-side provenance."""
from contextlib import closing
import json
import sqlite3

from factory.instruments.uvvis_adapter import InstrumentUnavailable
from factory.instruments.uvvis_contract import canonical, validate, validate_key, validate_pins


class ApprovedAcquisition:
    """Use one caller-supplied key per intended batch, including all retries."""

    def __init__(self, specifications, sqlite_path, adapter):
        self.specifications = specifications
        self.sqlite_path = sqlite_path
        self.adapter = adapter
        with closing(sqlite3.connect(sqlite_path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS approved_acquisitions (
                submission_key TEXT PRIMARY KEY NOT NULL,
                specification_sha256 TEXT NOT NULL,
                provenance TEXT NOT NULL,
                blank TEXT NOT NULL,
                request TEXT NOT NULL,
                job_id TEXT UNIQUE
            )""")

    def _blank(self, recipe, calibration):
        if calibration is not None:
            # The instrument checks existence and optical compatibility on submission.
            # Retain the reference from the calibration with its source identity.
            if not calibration.get("blank_id"):
                raise ValueError("The approved calibration is missing its blank reference")
            return {"blank_id": calibration["blank_id"], "source": "frozen_calibration",
                    "calibration_id": calibration["id"], "calibration_sha256": calibration["sha256"]}
        settings = recipe["settings"]
        blank = self.adapter.blank(settings)
        validate_pins(recipe, blank)
        if any(blank[name] != settings[name] for name in ("wavelength_nm", "path_length_mm")):
            raise ValueError("Blank settings do not match the approved recipe")
        return blank

    def submit(self, spec_digest, *, key):
        """Submit a single batch (one timepoint), reusing the approved calibration's blank."""
        validate_key(key)
        spec, approval = self.specifications.approved(spec_digest)
        recipe = self.specifications.compile_recipe(spec_digest)
        validate_pins(recipe, self.adapter.pin)
        sample_ids = [row["sample_id"] for row in spec["standards"]] + spec["sample_ids"]
        calibration = spec["calibration"]
        with closing(sqlite3.connect(self.sqlite_path)) as db, db:
            # Serialize creation so competing clients persist the same reference for this key.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT specification_sha256, request, job_id
                                FROM approved_acquisitions WHERE submission_key=?""", (key,)).fetchone()
            if row is None:
                blank = self._blank(recipe, calibration)
                request = {**recipe, "blank_id": blank["blank_id"], "sample_ids": sample_ids}
                validate("acquisition_request", request)
                provenance = {"project": spec["project"], "lab": spec["lab"],
                              "specification_id": spec["specification_id"], "revision": spec["revision"],
                              "approval": approval}
                db.execute("""INSERT INTO approved_acquisitions
                              (submission_key, specification_sha256, provenance, blank, request)
                              VALUES (?, ?, ?, ?, ?)""",
                           (key, spec_digest, canonical(provenance), canonical(blank), canonical(request)))
            else:
                if row[0] != spec_digest:
                    raise ValueError("Submission key already belongs to a different specification")
                request = json.loads(row[1])
                if calibration is not None and request["blank_id"] != calibration.get("blank_id"):
                    raise ValueError("Saved submission does not use the approved calibration blank")
                if row[2] is not None:
                    return self.get(key)

        # The blank, exact request and key survive a lost response or a process restart.
        job = self.adapter.submit(request["settings"], request["sample_ids"], request["blank_id"], key)
        if any(job[field] != value for field, value in request.items()):
            raise ValueError("Instrument job does not match the submitted acquisition")
        with closing(sqlite3.connect(self.sqlite_path)) as db, db:
            updated = db.execute("""UPDATE approved_acquisitions SET job_id=?
                                    WHERE submission_key=? AND (job_id IS NULL OR job_id=?)""",
                                 (job["job_id"], key, job["job_id"]))
            if updated.rowcount != 1:
                raise ValueError("Submission already linked to a different instrument job")
        return self.get(key)

    def _request_for_job(self, job_id):
        with closing(sqlite3.connect(self.sqlite_path)) as db:
            row = db.execute("SELECT request FROM approved_acquisitions WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise InstrumentUnavailable("No approved request for this acquisition job")
        try:
            request = json.loads(row[0])
            validate("acquisition_request", request)
        except (ValueError, TypeError) as error:
            raise InstrumentUnavailable("Invalid saved acquisition request") from error
        return request

    def poll(self, job_id):
        return self.adapter.poll(job_id, expected_request=self._request_for_job(job_id))

    def cancel(self, job_id):
        return self.adapter.cancel(job_id, expected_request=self._request_for_job(job_id))

    def measurements(self, job_id):
        return self.adapter.measurements(job_id, expected_request=self._request_for_job(job_id))

    def get(self, key):
        """The instrument owns measurement records, indexed by this persisted job ID."""
        with closing(sqlite3.connect(self.sqlite_path)) as db:
            row = db.execute("""SELECT specification_sha256, provenance, blank, request, job_id
                                FROM approved_acquisitions WHERE submission_key=?""", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return {"submission_key": key, "specification_sha256": row[0], **json.loads(row[1]),
                "blank": json.loads(row[2]), "request": json.loads(row[3]), "job_id": row[4]}
