"""Reconcile an uncertain accepted POST across scheduler and adapter restarts."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from factory.experiments.approved_acquisition import ApprovedAcquisition
from factory.lab_context.context_repository import SQLiteContextRepository
from factory.experiments.experiment_adapters import LocalExperimentBackend
from factory.experiments.experiment_scheduler import ExperimentOrchestrator
from factory.lab_context.specifications import ExperimentSpecificationService
from factory.instruments.uvvis_service import VirtualUvVisService
from tests.test_context_acquisition_integration import live_instrument
from tests.test_context_repository import load_demo
from tests.test_uvvis_api import until


class SchedulerIdentityTests(unittest.TestCase):
    def test_uncertain_success_retains_lease_and_recovers_one_remote_job(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        app, queue, store = root / "app.sqlite", root / "queue.sqlite", root / "instrument"
        lab, project = load_demo(SQLiteContextRepository(app))
        specs = ExperimentSpecificationService(SQLiteContextRepository(app), app)
        spec = specs.start(lab.lab_id, project.project_id)
        sha, pin = spec["sha256"], spec["instrument"]
        specs.approve(sha, actor="researcher", confirmed_fields=specs.confirmation_fields(spec))

        def scheduler(adapter):
            saved = ExperimentSpecificationService(SQLiteContextRepository(app), app)
            backend = LocalExperimentBackend(app, saved, ApprovedAcquisition(saved, app, adapter), planner=None)
            # Isolate acquisition from software generation. Composition tests cover a real verifier.
            self.enterContext(patch.object(backend, "prepare", side_effect=RuntimeError("software offline")))
            return closing(ExperimentOrchestrator(queue, backend))

        accepted = []
        submit = VirtualUvVisService.submit

        def incomplete_response(service, request, key):
            job = submit(service, request, key)
            accepted.append(job.pop("job_id"))
            return job

        with live_instrument(store, pin, spec["standards"]) as adapter, scheduler(adapter) as worker:
            run = worker.submit("first-experiment", sha, pin["instrument_id"])
            other = worker.submit("waiting-experiment", sha, pin["instrument_id"])
            with patch.object(VirtualUvVisService, "submit", incomplete_response):
                worker.tick()
            pending = worker.status(run)
            self.assertEqual(pending["acquisition"], "uncertain")
            self.assertIsNone(pending["job_id"])
            self.assertEqual(worker.status(other)["acquisition"], "queued")
            with closing(sqlite3.connect(queue)) as db:
                self.assertEqual(db.execute("SELECT run_id FROM scheduling_leases").fetchall(), [(run,)])
            worker.cancel(other)
            # Finish the simulated batch before closing the service, despite the missing HTTP identity.
            until(lambda: adapter.poll(accepted[0])["status"] == "completed")

        with live_instrument(store, pin, spec["standards"]) as adapter, scheduler(adapter) as restarted:
            restarted.tick()
            recovered = restarted.status(run)
            self.assertEqual(recovered["acquisition"], "completed")
            self.assertEqual(set(accepted), {recovered["job_id"]})
            readings = recovered["measurements"]["records"]
            expected = (len(spec["standards"]) + len(spec["sample_ids"])) * spec["settings"]["replicates"]
            self.assertEqual(len(readings), expected)
            self.assertTrue(all(r["job_id"] == recovered["job_id"] for r in readings))
            with closing(sqlite3.connect(store / "jobs.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT id,submission_key FROM jobs").fetchall(),
                                 [(recovered["job_id"], pending["dispatch_key"])])
                self.assertEqual(db.execute("SELECT count(*) FROM blanks").fetchone(), (1,))
                self.assertEqual(db.execute("SELECT count(*) FROM readings").fetchone(), (expected,))
            with closing(sqlite3.connect(queue)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM scheduling_leases").fetchone(), (0,))
