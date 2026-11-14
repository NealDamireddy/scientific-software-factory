"""Check durable approval against live jobs and records after reopening the application."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from factory.approved_acquisition import ApprovedAcquisition
from factory.context import ROOT, read_json
from factory.context_repository import SQLiteContextRepository
from factory.experiment_adapters import LocalExperimentBackend
from factory.specifications import ExperimentSpecificationService
from factory.uvvis_adapter import InstrumentUnavailable, VirtualInstrumentAdapter
from factory.uvvis_service import VirtualUvVisService
from tests.test_context_acquisition_integration import live_instrument
from tests.test_specifications import save_calibration_fixture
from tests.test_uvvis_api import until


class ApprovedJobIdentityTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.db = root / "app.sqlite"
        self.store = root / "instrument"
        fixture = read_json(ROOT / "fixtures/context/demo.json")
        instance = f"approval-{uuid4().hex}"
        fixture["lab"]["instruments"][0]["instrument_id"] = instance
        fixture["project"]["instrument_id"] = instance
        repo = SQLiteContextRepository(self.db)
        lab = repo.save_lab(fixture["lab"], expected_revision=0)
        project = repo.save_project(fixture["project"], expected_revision=0)
        specs = ExperimentSpecificationService(repo, self.db)
        spec = specs.start(lab.lab_id, project.project_id)
        self.sha = spec["sha256"]
        specs.approve(self.sha, actor="researcher", confirmed_fields=specs.confirmation_fields(spec))
        self.spec = spec

    def start_service(self, *, duration_s=0):
        self.owner = self.enterContext(live_instrument(self.store, self.spec["instrument"], self.spec["standards"],
                                                      duration_s=duration_s))

    def reopen(self):
        pin = self.owner.pin
        adapter = VirtualInstrumentAdapter(f"http://127.0.0.1:{self.owner.port}", pin["instrument_id"],
                                           pin["profile_id"], pin["profile_sha256"])
        specs = ExperimentSpecificationService(SQLiteContextRepository(self.db), self.db)
        return LocalExperimentBackend(self.db, specs, ApprovedAcquisition(specs, self.db, adapter), planner=None)

    def test_reopened_backend_rejects_consistently_substituted_job_and_records(self):
        self.start_service()
        job_id = self.reopen().acquire(self.sha, "requested")
        until(lambda: self.owner.poll(job_id)["status"] == "completed")
        job = self.owner.poll(job_id)
        data = self.owner.measurements(job_id)
        backend = self.reopen()
        for field in ("wavelength_nm", "sample_id", "blank_id"):
            substituted, envelope = deepcopy(job), deepcopy(data)
            if field == "wavelength_nm":
                substituted["settings"][field] = 450
                for record in envelope["records"]:
                    record[field] = 450
            elif field == "blank_id":
                substituted[field] = "foreign-blank"
                for record in envelope["records"]:
                    record[field] = "foreign-blank"
            else:
                prior = substituted["sample_ids"][-1]
                substituted["sample_ids"][-1] = "foreign-vial"
                for record in envelope["records"]:
                    if record[field] == prior:
                        record[field] = "foreign-vial"
            with self.subTest(field=field), patch.object(VirtualUvVisService, "job", return_value=substituted), \
                    patch.object(VirtualUvVisService, "measurements", return_value=envelope):
                for operation in (backend.poll, backend.measurements):
                    with self.subTest(operation=operation.__name__), self.assertRaises(InstrumentUnavailable):
                        operation(job_id)

        self.assertEqual(backend.acquire(self.sha, "requested"), job_id)
        self.assertEqual(backend.poll(job_id), job)
        self.assertEqual(backend.measurements(job_id), data)
        with closing(sqlite3.connect(self.store / "jobs.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone(), (1,))

    def test_incomplete_or_missing_saved_request_blocks_lifecycle(self):
        self.start_service(duration_s=60)
        job_id = self.reopen().acquire(self.sha, "active")
        backend = self.reopen()
        with closing(sqlite3.connect(self.db)) as db:
            for payload in ("{", "null", "{}", None):
                with self.subTest(payload=payload):
                    with db:
                        if payload is None:
                            db.execute("DELETE FROM approved_acquisitions WHERE job_id=?", (job_id,))
                        else:
                            db.execute("UPDATE approved_acquisitions SET request=? WHERE job_id=?", (payload, job_id))
                    with self.assertRaises(InstrumentUnavailable):
                        backend.cancel(job_id)
                    self.assertEqual(self.owner.poll(job_id)["status"], "running")

    def test_reopened_series_rejects_changed_point_before_cancelling(self):
        self.start_service(duration_s=60)
        backend = self.reopen()
        spec = backend.specs.edit(self.sha, experiment_type="time_course")
        blank = self.owner.blank(spec["settings"])
        ref = save_calibration_fixture(self.db, spec, blank_id=blank["blank_id"])
        spec = backend.specs.edit(spec["sha256"], calibration=ref, schedule={"interval_s": 10, "point_count": 2})
        sha = spec["sha256"]
        backend.specs.approve(sha, actor="researcher", confirmed_fields=backend.specs.confirmation_fields(spec))
        with closing(sqlite3.connect(self.db)) as db:
            stored, = db.execute("SELECT payload FROM run_calibrations WHERE sha256=?", (ref["sha256"],)).fetchone()
        spec, _ = backend.specs.approved(sha)
        series = backend.series.submit(spec, backend.specs.compile_recipe(sha), json.loads(stored), "course")
        self.assertEqual(backend.poll(series)["status"], "running")
        point = backend.acquisitions.get(f"{series}-1")["job_id"]
        original = self.owner.poll(point)
        substituted = {**original, "settings": {**original["settings"], "wavelength_nm": 450}}
        reopened = self.reopen()
        with patch.object(VirtualUvVisService, "job", return_value=substituted):
            for operation in (reopened.poll, reopened.measurements, reopened.cancel):
                with self.subTest(operation=operation.__name__), self.assertRaises(InstrumentUnavailable):
                    operation(series)
        self.assertEqual(self.owner.poll(point)["status"], "running")
        self.assertEqual(reopened.cancel(series)["status"], "cancelled")
        self.assertEqual(self.owner.poll(point)["status"], "cancelled")
        self.assertFalse(reopened.measurements(series)["complete"])
