"""Exercise WO-8 through the saved public context and the real local instrument."""
from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from factory.experiments.approved_acquisition import ApprovedAcquisition
from factory.lab_context.context_repository import SQLiteContextRepository
from factory.lab_context.specifications import ExperimentSpecificationService
from factory.instruments.uvvis_adapter import InstrumentUnavailable, VirtualInstrumentAdapter
from factory.instruments.uvvis_contract import InstrumentError
from factory.instruments.uvvis_http import make_server
from factory.instruments.uvvis_service import VirtualUvVisService
from tests.test_context_repository import load_demo
from tests.test_specifications import save_calibration_fixture
from tests.test_uvvis_api import SAMPLES, until


@contextmanager
def live_instrument(store, instrument, standards, *, duration_s=0):
    # Public standard concentrations and simulator-only models are loaded on the instrument side.
    models = {**SAMPLES, **{s["sample_id"]: {"concentration_mg_l": s["known_concentration"]}
                            for s in standards}}
    with closing(VirtualUvVisService(store, models, duration_s=duration_s,
                                     instrument_id=instrument["instrument_id"])) as service, make_server(service) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield VirtualInstrumentAdapter(f"http://127.0.0.1:{server.server_port}", instrument["instrument_id"],
                                           instrument["profile_id"], instrument["profile_sha256"])
        finally:
            server.shutdown()
            thread.join()


def test_saved_project_context_drives_fresh_acquisition():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        db = root / "application.sqlite"
        job_store = root / "instrument"
        lab, project = load_demo(SQLiteContextRepository(db))
        # The repository closes connections per operation. Start with a new repository object.
        repo = SQLiteContextRepository(db)
        specs = ExperimentSpecificationService(repo, db)
        spec = specs.start(lab.lab_id, project.project_id)
        digest = spec["sha256"]
        assert spec["project"]["sha256"] == project.sha256
        assert spec["settings"] == project.payload["measurement_settings"]
        assert spec["settings"]["wavelength_nm"] == 650
        assert spec["sample_ids"] == project.payload["sample_ids"]
        assert spec["standards"] == project.payload["standards"]

        confirmed = ["experiment_type", "settings", "sample_ids", "standards", "units", "outputs", "validation_criteria"]
        approval = specs.approve(digest, actor="local-researcher", confirmed_fields=confirmed)
        assert approval["specification_sha256"] == digest and "settings" in approval["confirmed_fields"]
        approved_recipe = specs.compile_recipe(digest)
        assert approved_recipe["settings"] == project.payload["measurement_settings"]
        latest = repo.save_project({**project.payload, "protocol_revision": 2, "measurement_settings": {
            **project.payload["measurement_settings"], "wavelength_nm": 450}}, expected_revision=project.revision)
        assert latest.sha256 != project.sha256
        assert repo.get("project", lab.lab_id, project_id=project.project_id).sha256 == latest.sha256

        specs = ExperimentSpecificationService(SQLiteContextRepository(db), db)
        assert specs.compile_recipe(digest) == approved_recipe
        with live_instrument(job_store, spec["instrument"], spec["standards"]) as adapter:
            with closing(sqlite3.connect(job_store / "jobs.sqlite3")) as instrument_db:
                assert instrument_db.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
            acquisition = ApprovedAcquisition(specs, db, adapter)
            before = datetime.now(timezone.utc)
            key = "approved-protocol-1"
            trace = acquisition.submit(digest, key=key)
            job_id = trace["job_id"]
            until(lambda: adapter.poll(job_id)["status"] == "completed")
            job = adapter.poll(job_id)
            measurements = adapter.measurements(job_id)
            after = datetime.now(timezone.utc)

            assert trace == ApprovedAcquisition(specs, db, adapter).get(key)
            assert trace["project"]["revision_id"] == project.revision_id
            assert trace["project"]["revision"] == project.revision
            assert trace["project"]["sha256"] == project.sha256
            assert trace["lab"]["sha256"] == lab.sha256
            assert trace["specification_sha256"] == digest
            assert trace["approval"] == approval == specs.approved(digest)[1]
            unknown, = project.payload["sample_ids"]
            selected = [s["sample_id"] for s in project.payload["standards"]] + [unknown]
            request = trace["request"]
            blank = trace["blank"]
            assert request == {**approved_recipe, "blank_id": blank["blank_id"], "sample_ids": selected}
            assert all(job[field] == value for field, value in request.items())
            assert blank["wavelength_nm"] == 650 and blank["path_length_mm"] == 10
            assert measurements["complete"] and measurements["job_id"] == job_id
            records = measurements["records"]
            assert Counter(r["sample_id"] for r in records) == dict.fromkeys(selected, 3)
            assert [r["replicate"] for r in records if r["sample_id"] == unknown] == [1, 2, 3]
            started = datetime.fromisoformat(job["started_at"])
            finished = datetime.fromisoformat(job["finished_at"])
            assert before <= datetime.fromisoformat(blank["timestamp"]) <= started <= finished <= after
            for record in records:
                assert started <= datetime.fromisoformat(record["timestamp"]) <= finished
                assert record["dark_counts"] == blank["dark_counts"]
                assert record["blank_counts"] == blank["blank_counts"]
                assert record["job_id"] == job_id and record["blank_id"] == blank["blank_id"]
                assert record["elapsed_s"] >= 0 and record["simulated"] is True
                assert record["wavelength_nm"] == 650 and record["path_length_mm"] == 10
                for field in ("instrument_id", "profile_id", "profile_sha256"):
                    assert record[field] == spec["instrument"][field] == blank[field]
            # Compare the actual wire submission and retained rows to the application trace.
            with closing(sqlite3.connect(job_store / "jobs.sqlite3")) as instrument_db:
                (saved_job, saved_key, payload), = instrument_db.execute(
                    "SELECT id,submission_key,request FROM jobs").fetchall()
                assert (saved_job, saved_key, json.loads(payload)) == (job_id, key, request)
                rows = instrument_db.execute("SELECT record FROM readings WHERE job_id=? ORDER BY ordinal", (job_id,))
                assert [json.loads(row[0]) for row in rows] == records


class AcquisitionBoundaryTests(unittest.TestCase):
    def test_timepoint_submits_the_reference_pinned_by_frozen_calibration(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        db = root / "application.sqlite"
        repo = SQLiteContextRepository(db)
        lab, project = load_demo(repo)
        specs = ExperimentSpecificationService(repo, db)
        concentration = specs.start(lab.lab_id, project.project_id)
        self.assertEqual(len(concentration["standards"]), 3)
        spec = specs.edit(concentration["sha256"], experiment_type="time_course")
        store = root / "jobs"
        adapter = self.enterContext(live_instrument(store, spec["instrument"], []))
        acquisitions = ApprovedAcquisition(specs, db, adapter)
        reference = adapter.blank(spec["settings"])
        other = adapter.blank({**spec["settings"], "wavelength_nm": 450})
        for blank_id, error in ((other["blank_id"], "incompatible reference"),
                                ("absent-reference", "unknown reference"), (reference["blank_id"], None)):
            with self.subTest(blank_id=blank_id):
                calibration = save_calibration_fixture(db, spec, id="cal-1", blank_id=blank_id)
                spec = specs.edit(spec["sha256"], calibration=calibration, schedule={"interval_s": 5, "point_count": 3})
                specs.approve(spec["sha256"], actor="local-researcher", confirmed_fields=specs.confirmation_fields(spec))
                key = f"point-1-{blank_id}"
                if error:
                    with self.assertRaisesRegex(InstrumentError, error):
                        acquisitions.submit(spec["sha256"], key=key)
                    self.assertIsNone(acquisitions.get(key)["job_id"])
                    continue
                trace = acquisitions.submit(spec["sha256"], key=key)
                self.assertEqual(trace["blank"], {"blank_id": blank_id, "source": "frozen_calibration",
                                                  "calibration_id": "cal-1", "calibration_sha256": calibration["sha256"]})
                self.assertEqual(trace["request"]["blank_id"], blank_id)
                self.assertEqual(trace["request"]["sample_ids"], project.payload["sample_ids"])
                until(lambda: adapter.poll(trace["job_id"])["status"] == "completed")
                result = adapter.measurements(trace["job_id"])
                self.assertTrue(result["complete"])
                self.assertEqual([row["replicate"] for row in result["records"]], [1, 2, 3])
                for row in result["records"]:
                    self.assertEqual(row["blank_id"], reference["blank_id"])
                    self.assertEqual(row["wavelength_nm"], reference["wavelength_nm"])
                    self.assertEqual(row["blank_counts"], reference["blank_counts"])
        with closing(sqlite3.connect(store / "jobs.sqlite3")) as instrument_db:
            self.assertEqual(instrument_db.execute("SELECT count(*) FROM blanks").fetchone(), (2,))
            self.assertEqual(instrument_db.execute("SELECT count(*) FROM jobs").fetchone(), (1,))

    def test_retry_after_accepted_job_and_draft_or_adapter_rejection(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        db = root / "application.sqlite"
        repo = SQLiteContextRepository(db)
        lab, project = load_demo(repo)
        specs = ExperimentSpecificationService(repo, db)
        spec = specs.start(lab.lab_id, project.project_id)
        digest = spec["sha256"]
        store = root / "jobs"
        adapter = self.enterContext(live_instrument(store, spec["instrument"], spec["standards"]))
        acquisitions = ApprovedAcquisition(specs, db, adapter)
        with self.assertRaises(ValueError):
            acquisitions.submit(digest, key="unapproved")
        specs.approve(digest, actor="local-researcher", confirmed_fields=specs.confirmation_fields(spec))
        other = VirtualInstrumentAdapter(f"http://127.0.0.1:{adapter.port}", "other-instance",
                                         adapter.pin["profile_id"], adapter.pin["profile_sha256"])
        with self.assertRaisesRegex(InstrumentError, "instrument_id"):
            ApprovedAcquisition(specs, db, other).submit(digest, key="mismatched")
        with closing(sqlite3.connect(store / "jobs.sqlite3")) as instrument_db:
            self.assertEqual(instrument_db.execute("SELECT count(*) FROM blanks").fetchone(), (0,))

        submit = adapter.submit

        def lose_response(*args):
            submit(*args)
            raise InstrumentUnavailable("lost after submission")

        with patch.object(adapter, "submit", side_effect=lose_response), self.assertRaises(InstrumentUnavailable):
            acquisitions.submit(digest, key="retry")
        saved = acquisitions.get("retry")
        self.assertIsNone(saved["job_id"])
        reopened = ApprovedAcquisition(specs, db, adapter)
        trace = reopened.submit(digest, key="retry")
        self.assertEqual(trace["request"], saved["request"])
        self.assertEqual(reopened.submit(digest, key="retry"), trace)
        until(lambda: adapter.poll(trace["job_id"])["status"] == "completed")
        with closing(sqlite3.connect(store / "jobs.sqlite3")) as instrument_db:
            self.assertEqual(instrument_db.execute("SELECT id FROM jobs").fetchall(), [(trace["job_id"],)])
            self.assertEqual(instrument_db.execute("SELECT id FROM blanks").fetchall(), [(trace["blank"]["blank_id"],)])


def load_tests(loader, tests, pattern):
    # Keep the module-level pytest node ID runnable via the repository's unittest discovery too.
    tests.addTest(unittest.FunctionTestCase(test_saved_project_context_drives_fresh_acquisition))
    return tests
