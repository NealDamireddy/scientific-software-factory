"""Regenerate with python -m tests.test_workspace_golden --write from the repository root."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from factory.context import digest
from factory.context_repository import SQLiteContextRepository, canonical_json
from factory.specifications import ExperimentSpecificationService
from tests.test_context_repository import load_demo
from tests.test_specifications import save_calibration_fixture


GOLDEN = Path(__file__).resolve().parents[1] / "fixtures/workspace/producer-records.json"


def generate(folder):
    path = Path(folder) / "workspace.sqlite"
    repo = SQLiteContextRepository(path)
    # Control only public fixture identity and observation time. Producer services
    # still own serialization, pin resolution, validation, approval and digests.
    with patch("factory.context_repository.uuid4", side_effect=[
        "dc84e448-5541-4e4d-a3cb-3c942f1058fa", "56c2a294-a9bb-4223-a58d-aa3add5e29f3",
    ]):
        lab, project = load_demo(repo)
    service = ExperimentSpecificationService(repo, path)
    with patch("factory.specifications.uuid4", side_effect=["spec-concentration", "spec-time-course"]):
        concentration = service.start(lab.lab_id, project.project_id)
        initial_course = service.start(lab.lab_id, project.project_id, experiment_type="time_course")
    # WO-8's own persisted fit fixture exercises the same on-disk calibration
    # reference resolver as real runs. Its fit is synthetic fixture data.
    reference = save_calibration_fixture(path, concentration, id="cal-visible-01", blank_id="blank-101")
    course = service.edit(initial_course["sha256"], calibration=reference, schedule={"interval_s": 30, "point_count": 2})
    records = []
    for spec, hour, minute in [(concentration, 8, 59), (course, 9, 4)]:
        when = datetime(2026, 11, 12, hour, minute, 45, tzinfo=timezone.utc)
        with patch("factory.specifications.datetime") as clock:
            clock.now.return_value = when
            service.approve(spec["sha256"], actor="Fixture researcher", confirmed_fields=service.confirmation_fields(spec))
        persisted, approval = service.approved(spec["sha256"])
        payload = {k: v for k, v in persisted.items() if k not in ("sha256", "status")}
        records.append({"payload": payload, "sha256": persisted["sha256"], "approval": approval})

    original = service.get(initial_course["sha256"])
    records.insert(1, {"payload": {k: v for k, v in original.items() if k not in ("sha256", "status")},
                       "sha256": original["sha256"], "approval": None,
                       "unresolved_fields": service.unresolved(original)})
    with closing(sqlite3.connect(path)) as db:
        fit_bytes, = db.execute("SELECT payload FROM run_calibrations WHERE sha256=?", (reference["sha256"],)).fetchone()
    return {
        "lab": asdict(lab), "project": asdict(project), "specifications": records,
        "calibration": {"payload": json.loads(fit_bytes), "reference": reference},
    }


class WorkspaceGoldenTests(unittest.TestCase):
    def test_export_matches_producer_records_and_digest_inputs(self):
        with TemporaryDirectory() as folder:
            actual = generate(folder)
        self.assertEqual(actual, json.loads(GOLDEN.read_text()))
        for spec in actual["specifications"]:
            self.assertEqual(digest(canonical_json(spec["payload"]).encode()), spec["sha256"])
            if spec["approval"]:
                self.assertEqual(spec["approval"]["specification_sha256"], spec["sha256"])
        fit = actual["calibration"]
        self.assertEqual(digest(canonical_json(fit["payload"]).encode()), fit["reference"]["sha256"])
        self.assertEqual(actual["specifications"][-1]["payload"]["calibration"], fit["reference"])


if __name__ == "__main__" and sys.argv[1:] == ["--write"]:
    with TemporaryDirectory() as folder:
        GOLDEN.write_text(json.dumps(generate(folder), indent=2, sort_keys=True) + "\n")
