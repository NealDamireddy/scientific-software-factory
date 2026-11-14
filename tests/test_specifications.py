from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from factory.context import digest
from factory.context_repository import RevisionConflict, SQLiteContextRepository, canonical_json
from factory.specifications import ExperimentSpecificationService
from tests.test_context_repository import load_demo


def save_calibration_fixture(db_path, spec, *, blank_id="ref-1", **changes):
    """Persist a run-service-format frozen fit and return its public reference."""
    record = {
        "id": "frozen-cal", "contract": "absorbance-linear@1", "unit": "mg/L", "blank_id": blank_id,
        "lab_id": spec["lab"]["lab_id"], "project_id": spec["project"]["project_id"],
        **{k: spec["instrument"][k] for k in ("instrument_id", "profile_id", "profile_sha256")},
        **{k: spec["settings"][k] for k in ("wavelength_nm", "path_length_mm")},
        "slope": 0.02, "intercept": 0.01, "low": 0.03, "high": 0.2, "standards_sha256": "a" * 64,
        **changes,
    }
    payload = canonical_json(record)
    sha = digest(payload.encode())
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS run_calibrations (sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO run_calibrations VALUES (?, ?)", (sha, payload))
    return {
        **{k: record[k] for k in ("id", "contract", "unit", "instrument_id", "profile_sha256", "blank_id")},
        "settings": {k: record[k] for k in ("wavelength_nm", "path_length_mm")}, "sha256": sha,
    }


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

    def test_instrument_id_length_at_approval_and_compilation(self):
        for revision, length in enumerate((200, 201), start=1):
            with self.subTest(length=length):
                instrument_id = "i" * length
                instrument = {**self.lab.payload["instruments"][0], "instrument_id": instrument_id}
                self.context.save_lab({**self.lab.payload, "instruments": [instrument]}, expected_revision=revision)
                self.context.save_project({**self.project.payload, "instrument_id": instrument_id},
                                          expected_revision=revision)
                spec = self.start()
                if length == 200:
                    self.assertEqual(self.service.unresolved(spec), {})
                    self.approve(spec)
                    self.assertEqual(self.service.compile_recipe(spec["sha256"])["instrument_id"], instrument_id)
                else:
                    self.assertIn("too long", self.service.unresolved(spec)["instrument.instrument_id"])
                    with self.assertRaisesRegex(ValueError, r"instrument\.instrument_id"):
                        self.approve(spec)
                    with self.assertRaisesRegex(ValueError, "requires approval"):
                        self.service.approved(spec["sha256"])
                    self.assertEqual(self.service.get(spec["sha256"])["status"], "draft")

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

    def test_lists_all_incompatible_and_missing_settings_together(self):
        spec = self.start()
        revised = self.service.edit(spec["sha256"], settings={"operation": "scan", "wavelength_nm": 600,
                                                            "path_length_mm": 5, "replicates": 99})
        fields = {"settings.operation", "settings.wavelength_nm", "settings.path_length_mm", "settings.replicates"}
        self.assertEqual(self.service.unresolved(revised).keys(), fields)
        empty = self.service.edit(revised["sha256"], settings={})
        self.assertEqual(self.service.unresolved(empty).keys(), fields)

    def test_time_course_requires_confirmed_schedule_and_compatible_calibration(self):
        spec = self.start(experiment_type="time_course")
        self.assertEqual(set(self.service.unresolved(spec)), {"calibration", "schedule"})
        calibration = save_calibration_fixture(self.path, spec)
        bad = self.service.edit(spec["sha256"], calibration={**calibration, "settings": {}},
                                schedule={"interval_s": 0, "point_count": 101})
        self.assertEqual(set(self.service.unresolved(bad)), {"calibration", "schedule.interval_s", "schedule.point_count"})
        valid = self.service.edit(bad["sha256"], calibration=calibration, schedule={"interval_s": 1, "point_count": 100})
        missing_blank = {**valid, "calibration": {k: v for k, v in calibration.items() if k != "blank_id"}}
        self.assertIn("calibration", self.service.unresolved(missing_blank))
        self.assertIn("timestamp", valid["outputs"])
        receipt = self.approve(valid)
        self.assertLessEqual({"calibration", "schedule", "settings"}, set(receipt["confirmed_fields"]))

    def test_calibration_must_resolve_to_exact_frozen_record(self):
        spec = self.start(experiment_type="time_course")
        reference = save_calibration_fixture(self.path, spec)
        foreign = save_calibration_fixture(self.path, spec, project_id="other-project")
        for ref in (
            {**reference, "sha256": "f" * 64}, {**reference, "id": "invented"},
            {**reference, "blank_id": "invented-blank"}, foreign,
            save_calibration_fixture(self.path, spec, profile_id="other-profile"),
            save_calibration_fixture(self.path, spec, unit="g/L"),
            save_calibration_fixture(self.path, spec, instrument_id="other-instrument"),
            save_calibration_fixture(self.path, spec, wavelength_nm=450),
        ):
            with self.subTest(ref=ref):
                spec = self.service.edit(spec["sha256"], calibration=ref, schedule={"interval_s": 1, "point_count": 2})
                self.assertIn("calibration", self.service.unresolved(spec))
                with self.assertRaisesRegex(ValueError, "calibration"):
                    self.approve(spec)
                self.assertEqual(self.service.get(spec["sha256"])["status"], "draft")

        spec = self.service.edit(spec["sha256"], calibration=reference)
        self.approve(spec)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE run_calibrations SET payload=json_set(payload, '$.slope', 9) WHERE sha256=?",
                       (reference["sha256"],))
        with self.assertRaisesRegex(ValueError, "Frozen calibration differs"):
            self.service.compile_recipe(spec["sha256"])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM run_calibrations WHERE sha256=?", (reference["sha256"],))
        with self.assertRaisesRegex(ValueError, "existing frozen calibration"):
            self.service.approved(spec["sha256"])
