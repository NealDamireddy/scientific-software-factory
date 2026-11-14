import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from factory import b12_build
from factory.lab import Lab


class TaskTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Path(temporary.name)
        self.lab = Lab(self.store)
        self.addCleanup(self.lab.close)

    def test_failed_worker_preserves_failure_and_history(self):
        with patch("factory.b12_build.invoke_worker", side_effect=RuntimeError("worker unavailable")):
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
            with patch("factory.b12_build.invoke_worker", return_value=(candidate, {})), self.assertRaises(ValueError):
                b12_build.build("B12", self.store)
            self.assertFalse((self.store/"analysis.py").exists())
