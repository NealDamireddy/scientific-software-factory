"""Portable approval checks against historical detector counts and calibration."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from factory.context import ROOT, read_json
from factory.assays.b12.lab import Lab, save
from factory.assays.b12.optics import assess
from tests.b12_release_fixtures import verified_task


class ApprovalPrecisionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lab = Lab(directory.name)
        self.addCleanup(self.lab.close)
        bundle = read_json(ROOT / "public/b12/completed.json")
        self.direct = verified_task(bundle, "direct")
        self.data = bundle["initial"]
        self.folder = Path(directory.name) / self.direct["id"]
        self.folder.mkdir()
        for name, source in bundle["sources"][self.direct["id"]]["files"].items():
            (self.folder / name).write_text(source)
        save(self.folder / "task.json", self.direct)
        save(self.folder / "acquisition.json", self.data)

    def test_adjacent_libm_results_still_support_above_range_approval(self):
        # Model a bundle recorded on a second platform, one step from local log10.
        recomputed = assess(self.data["raw"], self.data["calibration"])
        saved = [math.nextafter(value, -math.inf) for value in recomputed["absorbances"]]
        self.direct["finding"]["absorbances"] = saved
        self.data["finding"] = deepcopy(self.direct["finding"])
        self.data["input"]["absorbances"] = saved
        save(self.folder / "task.json", self.direct)
        save(self.folder / "acquisition.json", self.data)
        with patch.object(self.lab.pool, "submit") as dispatch:
            child = self.lab.approve(self.direct["id"], factor=4)
        dispatch.assert_called_once()
        self.assertEqual(child["approval"]["evidence"]["readings"], saved)
        self.assertEqual(child["approval"]["evidence"]["calibration_id"], self.data["calibration"]["id"])

    def test_rejects_changed_readings_and_metadata(self):
        values = assess(self.data["raw"], self.data["calibration"])["absorbances"]
        beyond_rounding = math.nextafter(math.nextafter(values[0], math.inf), math.inf)
        for where, key, change in (
            ("task", "absorbances", [0.2] * 3),
            ("finding", "absorbances", [0.2] * 3),
            ("input", "absorbances", [0.2] * 3),
            ("input", "absorbances", [beyond_rounding, *values[1:]]),
            ("input", "absorbances", [True] * 3),
            ("input", "absorbances", [math.nan] * 3),
            ("finding", "absorbances", [math.inf] * 3),
            ("input", "absorbances", []),
            ("finding", "above_range", 1),
            ("finding", "in_range", True),
            ("input", "sample_id", "Other vial"),
            ("input", "calibration", {**self.data["input"]["calibration"], "id": "other calibration"}),
            ("input", "calibration", {**self.data["input"]["calibration"],
                                      "high": math.nextafter(self.data["calibration"]["high"], math.inf)}),
        ):
            with self.subTest(record=where, key=key, change=change):
                task, data = deepcopy(self.direct), deepcopy(self.data)
                data["finding"] = deepcopy(task["finding"])
                record = task["finding"] if where == "task" else data[where]
                record[key] = change
                save(self.folder / "task.json", task)
                # Exercise even malformed NaN/Infinity tokens accepted by json.loads.
                (self.folder / "acquisition.json").write_text(json.dumps(data))
                with patch.object(self.lab.pool, "submit") as dispatch:
                    with self.assertRaisesRegex(ValueError, "evidence does not support"):
                        self.lab.approve(task["id"], factor=4)
                dispatch.assert_not_called()
