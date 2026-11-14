from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from factory.context_repository import RevisionConflict, SQLiteContextRepository
from factory.specifications import ExperimentSpecificationService
from tests.test_context_repository import load_demo


class SpecificationTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.path = root / "project.sqlite"
        self.context = SQLiteContextRepository(self.path)
        self.lab, self.project = load_demo(self.context)
        self.service = ExperimentSpecificationService(self.context, self.path)

    def start(self, **options):
        return self.service.start(self.lab.lab_id, self.project.project_id, **options)

    def approve(self, spec):
        return self.service.approve(spec["sha256"], actor="local-researcher",
                                    confirmed_fields=self.service.confirmation_fields(spec))

    def test_draft_defaults_and_explicit_confirmation(self):
        minimal = dict(self.project.payload)
        for key in ("measurement_settings", "sample_ids", "standards"):
            del minimal[key]
        self.context.save_project(minimal, expected_revision=1)
        spec = self.start()
        self.assertEqual(spec["status"], "draft")
        self.assertEqual(spec["experiment_type"], "concentration")
        self.assertEqual(spec["settings"], {"replicates": 3, "path_length_mm": 10, "operation": "measure-absorbance"})
        self.assertLessEqual({"settings.wavelength_nm", "sample_ids", "standards"},
                             self.service.unresolved(spec).keys())
        with self.assertRaisesRegex(ValueError, "settings.wavelength_nm"):
            self.approve(spec)
        complete = self.start(project_revision=1)
        with self.assertRaisesRegex(ValueError, "confirmation"):
            self.service.approve(complete["sha256"], actor="local", confirmed_fields={"settings"})
        with self.assertRaisesRegex(ValueError, "actor"):
            self.service.approve(complete["sha256"], actor=" ", confirmed_fields=self.service.confirmation_fields(complete))
        with self.assertRaisesRegex(ValueError, "requires approval"):
            self.service.compile_recipe(complete["sha256"])

    def test_persisted_approval_and_revision_identity(self):
        spec = self.start()
        spec["settings"]["wavelength_nm"] = 450  # A displayed object cannot modify the reviewed record.
        approval = self.approve(spec)
        reopened = ExperimentSpecificationService(SQLiteContextRepository(self.path), self.path)
        saved, recorded = reopened.approved(spec["sha256"])
        self.assertEqual(recorded, approval)
        self.assertEqual(saved["status"], "approved")
        self.assertEqual(recorded["specification_sha256"], spec["sha256"])
        self.assertEqual(saved["project"]["revision_id"], self.project.revision_id)
        self.assertEqual(saved["lab"]["sha256"], self.lab.sha256)
        self.assertEqual(reopened.compile_recipe(spec["sha256"])["settings"]["wavelength_nm"], 650)
        revised = reopened.edit(spec["sha256"], sample_ids=["unknown-42"])
        self.assertEqual((revised["specification_id"], revised["revision"], revised["status"]),
                         (spec["specification_id"], 2, "draft"))
        with self.assertRaisesRegex(ValueError, "approval"):
            reopened.approved(revised["sha256"])
        self.assertEqual(self.approve(revised)["specification_sha256"], revised["sha256"])

    def test_stale_concurrent_edits_and_protected_pins(self):
        draft = self.start()
        def edit(sample):
            try:
                return self.service.edit(draft["sha256"], sample_ids=[sample])["revision"]
            except RevisionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(edit, ["new-1", "new-2"])), [2, "conflict"])
        with self.assertRaises(ValueError):
            self.service.edit(draft["sha256"], project={"revision": 999})

    def test_invalid_samples_capabilities_and_unsupported_types(self):
        spec = self.start()
        cases = [
            ("settings", {**spec["settings"], "wavelength_nm": 600}, "wavelength_nm"),
            ("settings", {**spec["settings"], "replicates": True}, "replicates"),
            ("settings", {**spec["settings"], "replicates": 11}, "replicates"),
            ("standards", [dict(s, known_concentration=1) for s in spec["standards"]], "standards"),
            ("sample_ids", ["std-1"], "standards"),
            ("sample_ids", ["x", "x"], "sample_ids"),
            ("experiment_type", "kinetics", "Unsupported experiment type"),
        ]
        for field, value, problem in cases:
            with self.subTest(field=field, value=value):
                spec = self.service.edit(spec["sha256"], **{field: value})
                with self.assertRaisesRegex(ValueError, problem):
                    self.approve(spec)
                spec = self.start()

    def test_time_course_requires_confirmed_schedule_and_compatible_calibration(self):
        spec = self.start(experiment_type="time_course")
        self.assertEqual(set(self.service.unresolved(spec)), {"calibration", "schedule"})
        calibration = {
            "id": "frozen-cal", "sha256": "3" * 64, "contract": "absorbance-linear@1", "unit": "mg/L",
            "settings": {"wavelength_nm": 650, "path_length_mm": 10},
            **{k: spec["instrument"][k] for k in ("instrument_id", "profile_sha256")},
        }
        bad = self.service.edit(spec["sha256"], calibration={**calibration, "settings": {}},
                                schedule={"interval_s": 0, "point_count": 101})
        self.assertEqual(set(self.service.unresolved(bad)), {"calibration", "schedule.interval_s", "schedule.point_count"})
        valid = self.service.edit(bad["sha256"], calibration=calibration, schedule={"interval_s": 1, "point_count": 100})
        self.assertIn("timestamp", valid["outputs"])
        receipt = self.approve(valid)
        self.assertLessEqual({"calibration", "schedule", "settings"}, set(receipt["confirmed_fields"]))
