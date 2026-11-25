"""Approved specification to immutable release, and sample-only reuse, on the current tree.

This replaces the CI step that ran ``scripts/check_wo8_wo9_handoff.py HEAD HEAD``. That
script composes two commits with ``git merge-tree``, so given the same commit twice its
composition check could never fail. WO-8 and WO-9 are both merged now, so the part worth
keeping is the handoff itself, exercised here against the checked-out code. The script
stays for composing two historical commits by hand (``tests/fixtures/wo15/capture.py``
imports it from a pinned checkout).
"""
from pathlib import Path
import tempfile
import unittest

from factory.lab_context.context_repository import SQLiteContextRepository
from factory.lab_context.specifications import ExperimentSpecificationService
from factory.software.release_repository import ReleaseRepository
from scripts.check_wo8_wo9_handoff import exercise
from tests.test_context_repository import load_demo

ROOT = Path(__file__).resolve().parents[1]


class ReleaseHandoffTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / "application.sqlite"
        context = SQLiteContextRepository(self.db)
        self.lab, self.project = load_demo(context)
        self.specs = ExperimentSpecificationService(context, self.db)
        self.releases = ReleaseRepository(self.db)

    def check(self, kind):
        report = exercise(ROOT, self.db, kind, self.specs, self.releases, self.lab, self.project)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["result_state"], "released")
        self.assertEqual(report["worker_calls"], 1)
        self.assertEqual(report["sample_only_reuse"]["mode"], "reuse")
        self.assertEqual(report["sample_only_reuse"]["worker_calls"], 0)

    def test_concentration_handoff_releases_then_reuses(self):
        self.check("concentration")

    def test_time_course_handoff_releases_then_reuses(self):
        self.check("time_course")


if __name__ == "__main__":
    unittest.main(verbosity=2)
