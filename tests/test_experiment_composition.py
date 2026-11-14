"""Real scheduler composition; also runs when WO-8 and WO-9 are present together."""
from contextlib import closing
from copy import deepcopy
from importlib.util import find_spec
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from factory.context_repository import SQLiteContextRepository
from factory.experiment_adapters import LocalExperimentBackend
from factory.experiment_scheduler import ExperimentOrchestrator


class PreparationContentionTests(unittest.TestCase):
    def test_join_inflight_claim_and_recover_a_crashed_verifier(self):
        planner = Mock()
        backend = LocalExperimentBackend.__new__(LocalExperimentBackend)
        backend.planner = planner
        def task(state, id="first", release_id=None):
            return dict(state=state, id=id, release_id=release_id)
        planner.plan.side_effect = [task("pending"), task("pending", "second")]
        planner.run.side_effect = [task("pending"), task("candidate_ready"), task("candidate_ready", "second")]
        planner.verify.side_effect = [task("candidate_ready"), task("released", "second", "digest")]
        planner.get.side_effect = [task("pending"), task("interrupted")]
        with patch("factory.experiment_adapters.time.sleep"):
            self.assertEqual(backend.prepare("approved"), "digest")
        planner.plan.assert_called_with("approved", retry_of="first")
        planner.releases.load.assert_called_once_with("digest")

    def test_missing_verifier_fails_the_attempt(self):
        backend = LocalExperimentBackend.__new__(LocalExperimentBackend)
        backend.planner = Mock(verifier=None)
        backend.planner.plan.return_value = {"state": "candidate_ready", "id": "task"}
        with self.assertRaisesRegex(ValueError, "verifier is unavailable"):
            backend.prepare("approved")


@unittest.skipUnless(find_spec("factory.specifications") and find_spec("factory.scientific_analysis"),
                     "Composition requires WO-8 approval/planner and WO-9 verified release services")
class CompositionTests(unittest.TestCase):
    def test_concentration_then_two_point_time_course(self):
        from factory.approved_acquisition import ApprovedAcquisition
        from factory.release_planner import ReleasePlanner
        from factory.release_repository import ReleaseRepository
        from factory.scientific_release import verify_release
        from factory.specifications import ExperimentSpecificationService
        from tests.test_context_acquisition_integration import live_instrument
        from tests.test_context_repository import load_demo

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        app = root / "application.sqlite"
        repo = SQLiteContextRepository(app)
        lab, project = load_demo(repo)
        specs = ExperimentSpecificationService(repo, app)
        first = specs.start(lab.lab_id, project.project_id)
        instrument = self.enterContext(live_instrument(root / "instrument", first["instrument"], first["standards"]))
        releases = ReleaseRepository(root / "releases.sqlite")
        source = (Path(__file__).parent / "fixtures/scientific_analysis.py").read_text()

        def fixture_worker(prompt, _schema):
            contract = json.JSONDecoder().raw_decode(prompt.split("within this contract.\n", 1)[1])[0]
            response = {"source": source, "recipe": contract["compiled_recipe"],
                        "views": {"title": "Fixture application", "metrics": contract["view_metrics"]}}
            return response, {"method": "fixture candidate for real release verification"}

        planner = ReleasePlanner(specs, releases, app, worker=fixture_worker, verifier=verify_release)
        backend = LocalExperimentBackend(app, specs, ApprovedAcquisition(specs, app, instrument), planner)
        worker = self.enterContext(closing(ExperimentOrchestrator(root / "scheduler.sqlite", backend)))

        def finish(spec, key):
            specs.approve(spec["sha256"], actor="local-researcher", confirmed_fields=specs.confirmation_fields(spec))
            rid = worker.submit(key, spec["sha256"], first["instrument"]["instrument_id"])
            deadline = time.monotonic() + 100
            while True:
                worker.tick()
                run = worker.status(rid)
                if run["analysis"] == "completed":
                    return run
                diagnostic = [(s, run[s]) for s in ("acquisition", "software", "analysis", "blockers")]
                self.assertFalse(any(run[s] == "failed" for s in ("acquisition", "analysis", "software")), diagnostic)
                self.assertLess(time.monotonic(), deadline, diagnostic)
                time.sleep(0.03)

        measured = finish(first, "concentration")
        self.assertIsNotNone(measured["result"]["results"][0]["concentration_mg_l"])
        calibration = measured["result"]["calibration_reference"]
        self.assertEqual(calibration["blank_id"], measured["measurements"]["records"][0]["blank_id"])
        ts = specs.start(lab.lab_id, project.project_id, experiment_type="time_course")
        ts = specs.edit(ts["sha256"], calibration=calibration, schedule={"point_count": 2, "interval_s": 1})
        traced = finish(ts, "time-course")
        points = traced["measurements"]["points"]
        self.assertEqual(len({point["job_id"] for point in points}), 2)
        self.assertNotIn(measured["job_id"], [p["job_id"] for p in points])
        self.assertEqual(traced["result"]["calibration_id"], measured["result"]["calibration_id"])
        self.assertNotEqual(traced["release_id"], measured["release_id"])
        self.assertEqual(traced["result"]["results"][0]["timestamp"], points[0]["records"][0]["timestamp"])
        self.assertEqual(traced["result"]["results"][1]["timestamp"], points[1]["records"][0]["timestamp"])
        self.assertTrue(all(r["concentration_mg_l"] is not None for r in traced["result"]["results"]))
        for run in (measured, traced):
            manifest, _ = releases.load(run["release_id"])
            self.assertTrue(all(row["passed"] for row in manifest["checks"]))
            self.assertEqual(manifest["worker_receipt"]["method"], "fixture candidate for real release verification")
        with self.assertRaisesRegex(ValueError, "Incompatible verified release"):
            backend.analyze(ts["sha256"], measured["release_id"], traced["measurements"])

        incomplete = deepcopy(traced["measurements"])
        incomplete["points"].pop()
        with self.assertRaisesRegex(ValueError, "Incomplete or duplicated timepoints"):
            backend.analyze(ts["sha256"], traced["release_id"], incomplete)
        # A concentration rerun uses the frozen blank but fits its own fresh standards.
        repeated = specs.edit(first["sha256"], calibration=calibration)
        refitted = finish(repeated, "concentration-again")
        new_ref = refitted["result"]["calibration_reference"]
        self.assertEqual(new_ref["blank_id"], calibration["blank_id"])
        self.assertEqual(refitted["result"]["calibration_id"], new_ref["id"])
        self.assertEqual(new_ref["id"], "cal-" + refitted["job_id"])
        self.assertNotEqual(new_ref["sha256"], calibration["sha256"])
        self.assertNotEqual(new_ref["id"], calibration["id"])
        # A stored fit still has to match the approved digest at use time.
        with closing(sqlite3.connect(app)) as db, db:
            (raw,) = db.execute("SELECT payload FROM run_calibrations WHERE sha256=?", (calibration["sha256"],)).fetchone()
            altered = dict(json.loads(raw), slope=0.5)
            db.execute("UPDATE run_calibrations SET payload=? WHERE sha256=?", (json.dumps(altered), calibration["sha256"]))
        gate = backend.inspect(ts["sha256"], first["instrument"]["instrument_id"])
        self.assertFalse(gate["calibration_ready"])
        self.assertIn("Frozen calibration differs", gate["blocker"])
        with self.assertRaisesRegex(ValueError, "Frozen calibration differs"):
            backend.analyze(ts["sha256"], traced["release_id"], traced["measurements"])
