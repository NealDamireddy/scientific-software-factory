"""Verify facts carried by successful v1 job and measurement responses over HTTP."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from factory.instruments.uvvis_adapter import InstrumentUnavailable, VirtualInstrumentAdapter
from factory.instruments.uvvis_http import InstrumentHandler
from tests.test_uvvis_api import SETTINGS, instrument, until


class JobValidationTests(unittest.TestCase):
    def setUp(self):
        store = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.gate = threading.Event()
        self.gate.set()
        service, origin = self.enterContext(instrument(
            store, instrument_id="validation-" + uuid4().hex, duration_s=0,
            wait=lambda stop, duration: self.gate.wait(5),
        ))
        self.addCleanup(self.gate.set)
        self.service = service
        pin = service.pin
        self.api = VirtualInstrumentAdapter(f"http://127.0.0.1:{origin.port}", pin["instrument_id"],
                                            pin["profile_id"], pin["profile_sha256"])
        self.blank_id = self.api.blank(SETTINGS)["blank_id"]

    def submit(self):
        job = self.api.submit(SETTINGS, ["vial-q17"], self.blank_id, "validation")
        return job["job_id"]

    def completed(self):
        job_id = self.submit()
        until(lambda: self.service.job(job_id)["status"] == "completed")
        return self.api.poll(job_id), self.api.measurements(job_id)

    def test_complete_envelope_requires_a_completed_job(self):
        job, data = self.completed()
        for status in ("cancelled", "interrupted", "running"):
            with self.subTest(status=status), patch.object(self.service, "job", return_value={**job, "status": status}):
                with patch.object(self.service, "measurements", return_value=data):
                    with self.assertRaises(InstrumentUnavailable):
                        self.api.measurements(job["job_id"])

    def test_completed_job_requires_a_complete_nonempty_result(self):
        job, data = self.completed()
        for changes in ({"complete": False}, {"records": []}):
            with self.subTest(changes=changes), patch.object(self.service, "measurements", return_value={**data, **changes}):
                with self.assertRaises(InstrumentUnavailable):
                    self.api.measurements(job["job_id"])

    def test_completion_between_http_reads_is_confirmed(self):
        self.gate.clear()
        job_id = self.submit()
        route = InstrumentHandler._route
        statuses = []

        def finish_after_first_poll(handler):
            status, payload = route(handler)
            if handler.path.partition("?")[0] == f"/v1/acquisitions/{job_id}":
                statuses.append(payload["status"])
                if len(statuses) == 1:
                    self.gate.set()
                    until(lambda: self.service.job(job_id)["status"] == "completed")
            return status, payload

        with patch.object(InstrumentHandler, "_route", finish_after_first_poll):
            data = self.api.measurements(job_id)
        self.assertTrue(data["complete"])
        self.assertEqual(len(data["records"]), SETTINGS["replicates"])
        self.assertEqual(statuses, ["running", "completed"])

    def test_confirming_poll_must_match_the_initial_job_recipe(self):
        job, _ = self.completed()
        route = InstrumentHandler._route
        snapshots = iter(({**job, "status": "running", "finished_at": None},
                          {**job, "settings": {**SETTINGS, "wavelength_nm": 450}}))

        def substitute_on_poll(handler):
            if handler.path.partition("?")[0] == f"/v1/acquisitions/{job['job_id']}":
                return 200, next(snapshots)
            return route(handler)

        with patch.object(InstrumentHandler, "_route", substitute_on_poll):
            with self.assertRaisesRegex(InstrumentUnavailable, "settings"):
                self.api.measurements(job["job_id"])

    def test_invalid_sample_list_rejected_before_trusting_records(self):
        job, data = self.completed()
        for samples in ([], ["vial-q17", "vial-q17"], [f"vial-{i}" for i in range(101)]):
            with self.subTest(samples=len(samples)), patch.object(self.service, "job", return_value={**job, "sample_ids": samples}):
                with self.assertRaises(InstrumentUnavailable):
                    self.api.poll(job["job_id"])
                records = [] if not samples else data["records"]
                with patch.object(self.service, "measurements", return_value={**data, "records": records}):
                    with self.assertRaises(InstrumentUnavailable):
                        self.api.measurements(job["job_id"])

    def test_job_settings_must_be_supported_even_if_records_agree(self):
        job, data = self.completed()
        for field, value in (("operation", "scan"), ("path_length_mm", 8), ("replicates", 11), ("wavelength_nm", 600)):
            changed_job = {**job, "settings": {**job["settings"], field: value}}
            records = [{**r, field: value} if field in r else r for r in data["records"]]
            with self.subTest(field=field), patch.object(self.service, "job", return_value=changed_job):
                with self.assertRaises(InstrumentUnavailable):
                    self.api.poll(job["job_id"])
                with patch.object(self.service, "measurements", return_value={**data, "records": records}):
                    with self.assertRaises(InstrumentUnavailable):
                        self.api.measurements(job["job_id"])

    def test_cancel_response_preserves_checked_request(self):
        job, _ = self.completed()
        substituted = {**job, "sample_ids": ["vial-m"]}
        with patch.object(self.service, "cancel", return_value=substituted), self.assertRaises(InstrumentUnavailable):
            self.api.cancel(job["job_id"])
