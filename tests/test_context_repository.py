import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from jsonschema import Draft202012Validator

from factory.context import ROOT, read_json
from factory.context_repository import RevisionConflict, SQLiteContextRepository


def load_demo(repository):
    """Populate a new repository from public context and return its two pinned revisions."""
    fixture = read_json(ROOT / "fixtures/context/demo.json")
    lab = repository.save_lab(fixture["lab"], expected_revision=0)
    project = repository.save_project(fixture["project"], expected_revision=0)
    return lab, project


class RepositoryContract:
    """Implement open_repository() against one shared test store to reuse these checks."""

    def setUp(self):
        self.repo = self.open_repository()
        self.lab, self.project = load_demo(self.repo)

    def test_reopen_pinned_project_and_lab_after_edits(self):
        updated_lab = {**self.lab.payload, "name": "Renamed Optics Lab"}
        self.repo.save_lab(updated_lab, expected_revision=1)
        updated_project = copy.deepcopy(self.project.payload)
        updated_project["measurement_settings"]["wavelength_nm"] = 450
        revised = self.repo.save_project(updated_project, expected_revision=1)
        reopened = self.open_repository()
        self.assertEqual(reopened.get("project", "demo-lab", project_id="visible-assay"), revised)
        original = reopened.get("project", "demo-lab", project_id="visible-assay", revision=1)
        lab = reopened.get("lab", original.lab_id, revision=original.lab_revision)
        self.assertEqual(original, self.project)
        self.assertEqual(lab, self.lab)
        self.assertEqual(original.lab_sha256, lab.sha256)
        self.assertEqual(original.payload["measurement_settings"]["wavelength_nm"], 650)
        self.assertEqual(revised.lab_revision, 2)
        self.assertNotEqual(original.revision_id, revised.revision_id)
        self.assertNotEqual(original.sha256, revised.sha256)

    def test_project_sharing_and_scope(self):
        other = {**self.project.payload, "project_id": "second-assay"}
        second = self.repo.save_project(other, expected_revision=0)
        self.assertEqual(second.lab_sha256, self.project.lab_sha256)
        self.assertEqual(second.payload["instrument_id"], self.project.payload["instrument_id"])
        foreign = copy.deepcopy(self.lab.payload)
        foreign["lab_id"] = "other-lab"
        foreign["instruments"][0].update(lab_id="other-lab", instrument_id="uvvis-demo-02")
        self.repo.save_lab(foreign, expected_revision=0)
        with self.assertRaisesRegex(ValueError, "select an instrument in lab 'other-lab'"):
            self.repo.save_project({**other, "lab_id": "other-lab"}, expected_revision=0)
        with self.assertRaises(KeyError):
            self.repo.get("project", "other-lab", project_id="second-assay")
        foreign["instruments"][0]["instrument_id"] = "uvvis-demo-01"
        with self.assertRaisesRegex(ValueError, "belongs to another lab"):
            self.repo.save_lab(foreign, expected_revision=1)
        self.assertEqual(self.repo.get("lab", "other-lab").revision, 1)

    def test_required_fields_invalid_values_and_extra_fields(self):
        for record, writer in [(self.lab, self.repo.save_lab), (self.project, self.repo.save_project)]:
            required = read_json(ROOT / "registry/context.schema.json")["$defs"][record.kind]["required"]
            for field in required:
                payload = {k: v for k, v in record.payload.items() if k != field}
                with self.subTest(kind=record.kind, field=field), self.assertRaisesRegex(ValueError, field):
                    writer(payload, expected_revision=1)
        for field, invalid in [("scientific_objective", " "), ("units", {}), ("protocol_revision", True),
                               ("validation_criteria", []), ("analysis_method", None), ("seed", 7)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.repo.save_project({**self.project.payload, field: invalid}, expected_revision=1)
        lab = copy.deepcopy(self.lab.payload)
        lab["instruments"][0]["base_url"] = "http://localhost:1010"
        with self.assertRaisesRegex(ValueError, "base_url"):
            self.repo.save_lab(lab, expected_revision=1)
        with self.assertRaisesRegex(ValueError, "save lab"):
            self.repo.save_project({**self.project.payload, "lab_id": "missing"}, expected_revision=0)
        self.assertEqual(self.repo.get("project", "demo-lab", project_id=self.project.project_id), self.project)

    def test_reject_mismatched_profile_and_ownership(self):
        for key, value in [("profile_id", "virtual-uvvis@2"), ("profile_sha256", "b" * 64),
                           ("lab_id", "other-lab")]:
            lab = copy.deepcopy(self.lab.payload)
            lab["instruments"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.repo.save_lab(lab, expected_revision=1)
        duplicate = {**self.lab.payload, "instruments": self.lab.payload["instruments"] * 2}
        with self.assertRaisesRegex(ValueError, "duplicate instrument_id"):
            self.repo.save_lab(duplicate, expected_revision=1)
        self.assertEqual(self.repo.get("lab", "demo-lab"), self.lab)

    def test_stale_writes_fail_without_overwriting(self):
        for record, writer in [(self.lab, self.repo.save_lab), (self.project, self.repo.save_project)]:
            with self.assertRaisesRegex(RevisionConflict, "reload"):
                writer(record.payload, expected_revision=0)
            for value in (None, False, -1):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "expected_revision"):
                    writer(record.payload, expected_revision=value)

    def test_competing_connections_cannot_lose_updates(self):
        ready = threading.Barrier(2, timeout=5)

        def update(name):
            repo = self.open_repository()
            ready.wait()
            try:
                return repo.save_project({**self.project.payload, "analysis_method": name}, expected_revision=1)
            except RevisionConflict:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(update, ["method-a", "method-b"]))
        winners = [result for result in outcomes if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].revision, 2)
        self.assertEqual(self.repo.get("project", "demo-lab", project_id=self.project.project_id), winners[0])

    def test_payload_digest_is_independent_of_json_key_order(self):
        payload = dict(reversed(list(self.lab.payload.items())))
        result = self.repo.save_lab(payload, expected_revision=1)
        self.assertEqual(result.sha256, self.lab.sha256)
        self.assertNotEqual(result.revision_id, self.lab.revision_id)


class SQLiteRepositoryTests(RepositoryContract, unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "context.sqlite"
        super().setUp()

    def open_repository(self):
        return SQLiteContextRepository(self.path)

    def test_migrations_and_immutable_history(self):
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("pragma user_version").fetchone()[0], 1)
            for statement in ["DELETE FROM context_revisions", "UPDATE context_revisions SET revision=2"]:
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute(statement)
            db.execute("pragma user_version = 2")
        with self.assertRaisesRegex(ValueError, "Unsupported context database version"):
            self.open_repository()


class PublicProfileTests(unittest.TestCase):
    def test_frozen_public_projection(self):
        profile = read_json(ROOT / "registry/virtual-uvvis.profile.json")
        schema = read_json(ROOT / "registry/instrument-profile.schema.json")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(profile)
        self.assertFalse(validator.is_valid({**profile, "seed": 5}))
        fixture = read_json(ROOT / "fixtures/context/demo.json")
        instrument = fixture["lab"]["instruments"][0]
        self.assertEqual(instrument["profile_sha256"],
                         "d441df2219b76210b43c95cbd8f57758b68d3bfb772c343e85e3af67a3d23286")
        self.assertEqual(instrument["profile_id"], profile["profile_id"])
        schema = read_json(ROOT / "registry/context.schema.json")
        Draft202012Validator.check_schema(schema)
        for payload in fixture.values():
            Draft202012Validator(schema).validate(payload)
