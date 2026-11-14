"""Frozen-fit contract coverage and the trusted retained-release boundary."""
from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from factory.release_repository import ReleaseRepository
from factory.scientific_analysis import analyze_release
from factory.scientific_contract import cases, compare
from factory.scientific_release import verify_release
from tests.test_scientific_release import handoff


class FrozenCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.repo = ReleaseRepository(Path(self.enterContext(tempfile.TemporaryDirectory())) / "releases.sqlite")
        self.data = handoff("time_course")
        report = verify_release(self.repo, **self.data)
        self.release = report["release_id"]
        self.assertIsNotNone(self.release, [c for c in report["checks"] if not c["passed"]])
        self.probes = {name: (payload, expected)
                       for name, _, payload, expected in cases("time_course", self.data["compiled_recipe"])}

    def test_contract_changes_only_one_field_and_runtime_withholds_every_timepoint(self):
        clean, _ = self.probes["nonzero intercept, sample SD and identities"]
        for field in ("slope", "intercept", "low", "high"):
            for label, invalid in (("NaN", math.nan), ("positive infinite", math.inf),
                                   ("negative infinite", -math.inf)):
                with self.subTest(field=field, value=label):
                    payload, expected = self.probes[f"{label} frozen {field}"]
                    restored = deepcopy(payload)
                    actual = restored["calibration"][field]
                    if math.isnan(invalid):
                        self.assertTrue(math.isnan(actual))
                    else:
                        self.assertEqual(actual, invalid)
                    restored["calibration"][field] = clean["calibration"][field]
                    self.assertEqual(restored, clean)
                    with patch("factory.scientific_analysis.execute") as candidate:
                        result = analyze_release(self.repo, self.release, payload)
                        candidate.assert_not_called()
                    compare(result, expected)
                    self.assertEqual(result["calibration_id"], clean["calibration"]["id"])
                    for row, group in zip(result["results"], clean["groups"], strict=True):
                        self.assertEqual((row["sample_id"], row["timestamp"]),
                                         (group["sample_id"], group["records"][0]["timestamp"]))
                        self.assertIsNone(row["concentration_mg_l"])
                        self.assertIsNone(row["replicate_sd_mg_l"])
                        self.assertTrue(row["review_reason"].strip())

    def test_valid_endpoints_group_local_errors_and_unsupported_standards(self):
        for name in ("nonzero intercept, sample SD and identities", "alternate calibration, samples and acquisition times",
                     "below calibration range", "above calibration range", "positive frozen slope",
                     "negative frozen slope", "ordered calibration range", "equal calibration bounds"):
            with self.subTest(name=name):
                payload, expected = self.probes[name]
                compare(analyze_release(self.repo, self.release, payload), expected)
        conflicting, _ = self.probes["supplied standards cannot replace frozen fit"]
        with patch("factory.scientific_analysis.execute") as candidate:
            with self.assertRaisesRegex(ValueError, "empty standards"):
                analyze_release(self.repo, self.release, conflicting)
            candidate.assert_not_called()
