"""Upgrade persisted @5 approvals, preparations and releases produced by the pinned base."""
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from factory.lab_context.context_repository import SQLiteContextRepository
from factory.software.release_planner import ReleasePlanner
from factory.software.release_repository import ReleaseRepository
from factory.software.scientific_contract import VERIFIER
from factory.software.scientific_release import verify_release
from factory.lab_context.specifications import ExperimentSpecificationService


class FrozenCalibrationUpgradeTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(TemporaryDirectory()))
        self.path = folder / "application.sqlite"
        fixture = Path(__file__).parent / "fixtures/wo15/ae7d2f3.sql.gz"
        with gzip.open(fixture, "rt") as sql, closing(sqlite3.connect(self.path)) as db:
            db.executescript(sql.read())
        self.specs = ExperimentSpecificationService(SQLiteContextRepository(self.path), self.path)
        self.releases = ReleaseRepository(self.path)
        self.worker = Mock()
        self.planner = ReleasePlanner(self.specs, self.releases, self.path,
                                      worker=self.worker, verifier=verify_release)

    def active(self, kind):
        return self.releases.active("demo-lab", "visible-assay", kind)

    def sample_only_reuse(self, pin, approved_release):
        # The base handoff also stored a sample-only reuse. Make another approved
        # revision so this exercises a fresh compatibility decision on this version.
        spec, _ = self.specs.approved(pin)
        with closing(sqlite3.connect(self.path)) as db:
            latest, = db.execute("""SELECT digest FROM experiment_specifications WHERE specification_id=?
                                    ORDER BY revision DESC LIMIT 1""", (spec["specification_id"],)).fetchone()
        edited = self.specs.edit(latest, sample_ids=["post-upgrade-vial"])
        self.specs.approve(edited["sha256"], actor="upgrade-regression",
                           confirmed_fields=self.specs.confirmation_fields(edited))
        task = self.planner.plan(edited["sha256"])
        self.assertEqual((task["state"], task["mode"], task["release_id"]), ("reused", "reuse", approved_release))
        self.assertEqual(self.planner.run(task["id"]), task)
        self.worker.assert_not_called()

    def test_identical_time_course_approval_requires_current_certification(self):
        old = self.active("time_course")
        historical_manifest, historical_files = self.releases.load(old)
        self.assertEqual(historical_manifest["verifier_revision"], "scientific-release@5")
        context = historical_manifest["context"]
        old_task = self.planner.get(context["preparation_id"])
        self.assertEqual((old_task["state"], old_task["release_id"]), ("released", old))
        pin = context["specification_sha256"]

        task = self.planner.plan(pin)
        self.assertNotEqual(task["id"], old_task["id"])
        self.assertEqual((task["state"], task["mode"], task["parent_release_id"]), ("pending", "revise", old))
        self.assertIn("Incompatible verifier_revision", task["rejections"][old])
        self.worker.assert_not_called()
        self.worker.return_value = ({
            "source": historical_files["analysis.py"].decode(),
            "recipe": json.loads(historical_files["recipe.json"]),
            "views": json.loads(historical_files["views.json"]),
        }, {"method": "retained fixture source"})
        candidate = self.planner.run(task["id"])
        self.assertEqual(candidate["state"], "candidate_ready")
        self.worker.assert_called_once()
        self.assertEqual(self.active("time_course"), old)
        released = self.planner.verify(task["id"])
        self.assertEqual(released["state"], "released", released.get("verification"))
        new = released["release_id"]
        self.assertNotEqual(new, old)
        self.assertEqual(self.active("time_course"), new)
        manifest, files = self.releases.load(new)
        self.assertEqual(manifest["verifier_revision"], VERIFIER)
        self.assertEqual(manifest["context"]["specification_sha256"], pin)
        self.assertEqual(files, historical_files)
        self.assertEqual(manifest["source_revision"], historical_manifest["source_revision"])
        checks = {check["name"]: check for check in manifest["checks"]}
        self.assertTrue(all(check["status"] == "passed" for check in checks.values()))
        self.assertIn("supplied standards cannot replace frozen fit", checks)
        self.assertIn(checks["offline sandbox and trusted files"]["detail"], ("macOS Seatbelt", "Linux bubblewrap"))
        self.assertEqual(self.releases.load(old), (historical_manifest, historical_files))
        self.assertEqual(self.planner.get(old_task["id"]), old_task)
        self.worker.reset_mock()
        self.sample_only_reuse(pin, new)

    def test_historical_concentration_release_remains_reusable(self):
        release = self.active("concentration")
        historical = self.releases.load(release)
        manifest, _ = historical
        self.assertEqual(manifest["verifier_revision"], "scientific-release@5")
        self.sample_only_reuse(manifest["context"]["specification_sha256"], release)
        self.assertEqual(self.active("concentration"), release)
        self.assertEqual(self.releases.load(release), historical)
