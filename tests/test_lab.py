import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.b12_release_fixtures import verified_task

from factory.assays.b12 import b12_build
from factory.assays.b12.lab import Lab


class TaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Path(temporary.name)
        self.lab = Lab(self.store)
        self.addCleanup(self.lab.close)

    def test_failed_worker_preserves_failure_and_history(self):
        with patch("factory.assays.b12.b12_build.invoke_worker", side_effect=RuntimeError("worker unavailable")):
            task = self.lab.submit("Measure B12 with the registered instrument")
            self.lab.pool.shutdown()
        record = self.lab.task(task["id"])
        self.assertEqual(record["status"], "failed")
        self.assertIn("worker unavailable", record["error"])
        self.assertEqual(self.lab.history(), [record])
        self.assertFalse(self.lab.source(task["id"])["files"])

    def test_rejects_blank_and_traversal(self):
        with self.assertRaises(ValueError):
            self.lab.submit("  ")
        for brief in ("Use 361 nm", "Use 600nm"):
            with self.assertRaisesRegex(ValueError, "550 nm"):
                self.lab.submit(brief)
        with self.assertRaises(ValueError):
            self.lab.source("../outside")

    def test_rejects_bad_worker_recipe_and_view_before_writing(self):
        for recipe, metrics in [(dict(b12_build.RECIPE, wavelength_nm=600), b12_build.METRICS),
                                (b12_build.RECIPE, ["sample_id"])]:
            candidate = {"source":"print('{}')", "recipe":recipe, "views":{"title":"Assay", "metrics":metrics}}
            with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(candidate, {})), self.assertRaises(ValueError):
                b12_build.build("B12", self.store)
            self.assertFalse((self.store/"analysis.py").exists())

    def test_approval_reuses_child_and_retry_preserves_preparation(self):
        from factory.context import ROOT, read_json
        from factory.assays.b12.lab import save
        bundle = read_json(ROOT / "public/b12/completed.json")
        parent_id = bundle["direct"]["id"]
        parent = self.store/parent_id
        parent.mkdir()
        for name, source in bundle["sources"][parent_id]["files"].items():
            (parent/name).write_text(source)
        save(parent/"task.json", verified_task(bundle, "direct"))
        save(parent/"acquisition.json", bundle["initial"])
        with patch.object(self.lab.pool,"submit") as enqueue:
            child = self.lab.approve(parent_id)
            self.assertEqual(self.lab.approve(parent_id)["id"], child["id"])
            enqueue.assert_called_once()
        data = dict(sample_id="D",parent_id="U-01",sample_ml=1,final_ml=2,unit="mL")
        with self.assertRaises(ValueError):
            self.lab.prepare(child["id"], {**data,"final_ml":4})
        self.lab.prepare(child["id"], data)
        recorded = self.lab.task(child["id"])["preparation"]
        self.assertEqual(recorded["sample_id"],"D")
        self.assertEqual(self.lab.prepare(child["id"],data)["preparation"],recorded)
        with self.assertRaisesRegex(ValueError,"already recorded"):
            self.lab.prepare(child["id"], {**data,"sample_id":"another"})
        self.lab.update(child["id"],status="failed")
        with patch.object(self.lab.pool,"submit") as retry:
            self.assertEqual(self.lab.retry(child["id"])["preparation"],recorded)
            retry.assert_called_once()

    def test_rerun_and_label_require_the_correct_stage(self):
        from factory.assays.b12.lab import save
        uid = "c" * 32
        folder = self.store/uid
        folder.mkdir()
        task = {"id":uid,"created":"2026-11-01","status":"verifying","approval":{"factor":2}}
        save(folder/"task.json", task)
        for status, preparation in [("verifying", {"id":"P"}), ("verified", None)]:
            self.lab.update(uid,status=status,preparation=preparation)
            with self.assertRaisesRegex(ValueError, "Both"):
                self.lab.rerun(uid)
            with self.assertRaisesRegex(ValueError, "in-range"):
                self.lab.reveal(uid)
            with self.assertRaises(ValueError):
                self.lab.evidence(uid)
        self.lab.update(uid,measurement={"raw":[]}, result={"status":"review"})
        with self.assertRaisesRegex(ValueError, "in-range"):
            self.lab.reveal(uid)
