from hashlib import sha256
from pathlib import Path
import statistics
import tempfile
import unittest

from factory import benchmark
from factory.context import ROOT, read_json


class BenchmarkTests(unittest.TestCase):
    def test_archived_estimator_and_real_external_rows(self):
        package = ROOT / "public/b12/completed.json"
        bundle = read_json(package)
        cal = bundle["initial"]["calibration"]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "scored"
            report = benchmark.evaluate(package, out)
            for name in ("predictions", "registration"):
                self.assertEqual(report["hashes"][name + "_sha256"], sha256((out / (name + ".json")).read_bytes()).hexdigest())
            predictions = read_json(out / "predictions.json")
            for section in ("published", "panel"):
                for row in predictions[section]:
                    for label in ("prepared_mg_l", "prepared_ppm", "seed", "signed_error_mg_l"):
                        self.assertNotIn(label, row)
            self.assertEqual(report["source_revision"], bundle["followup"]["revision"])
            self.assertEqual(report["calibration_id"], cal["id"])
            panel = report["panel"]
            self.assertEqual([row["prepared_mg_l"] for row in panel["rows"]], [8, 12, 18, 22])
            self.assertTrue(panel["target_met"])
            for row in panel["rows"]:
                self.assertEqual(len(row["raw"]), 3)
                self.assertAlmostEqual(row["replicate_sd_mg_l"], statistics.stdev(row["absorbances"]) / cal["slope"])
            published = report["published"]
            self.assertEqual([(r["mean_absorbance"], r["prepared_ppm"]) for r in published["rows"]],
                             [(0.033, 3), (0.062, 5), (0.089, 10), (0.119, 15), (0.173, 20), (0.200, 24)])
            errors = []
            for row in published["rows"]:
                expected = (row["mean_absorbance"] - cal["intercept"]) / cal["slope"]
                self.assertAlmostEqual(row["predicted_mg_l"], expected)
                self.assertAlmostEqual(row["signed_error_mg_l"], expected - row["prepared_ppm"])
                errors.append(abs(expected - row["prepared_ppm"]))
                if row["extrapolated"]:
                    self.assertEqual(row["released_status"], "review")
                    self.assertIsNone(row["released_mg_l"])
                else:
                    self.assertEqual(row["released_status"], "ok")
            self.assertAlmostEqual(published["mae_mg_l"], statistics.mean(errors))
            self.assertEqual(sum(row["extrapolated"] for row in published["rows"]), 2)
            with self.assertRaises(FileExistsError):
                benchmark.evaluate(package, out)
            self.assertEqual(read_json(out / "report.json"), report)

    def test_withheld_or_unmatched_predictions_are_never_scored_as_success(self):
        samples = [{"id": "x", "prepared_mg_l": 22}]
        predictions = [{"id": "x", "predicted_mg_l": None}]
        rows, mae = benchmark._join_labels(predictions, samples, "prepared_mg_l")
        self.assertIsNone(mae)
        self.assertIsNone(rows[0]["signed_error_mg_l"])
        with self.assertRaisesRegex(ValueError, "match"):
            benchmark._join_labels(predictions * 2, samples, "prepared_mg_l")
