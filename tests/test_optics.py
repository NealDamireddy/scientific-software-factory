import math
import statistics
import tempfile
from pathlib import Path
import unittest

from factory.assays.b12 import optics


class OpticalTests(unittest.TestCase):
    def test_recipe_is_checked_again_at_acquisition(self):
        self.assertEqual(optics.validate_recipe(optics.RECIPE), optics.RECIPE)
        for changed in ({"wavelength_nm": 361}, {"wavelength_nm": 600}, {"replicates": 4},
                        {"operation": "pulse"}, {"sample_label": "hidden"}):
            recipe = {**optics.RECIPE, **changed}
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    optics.validate_recipe(recipe)
                with self.assertRaises(ValueError):
                    optics.acquire(recipe, 12, 7)

    def test_acquisition_metadata_and_seeded_counts(self):
        def counts(raw):
            return [[r[k] for k in ("dark_counts", "blank_counts", "sample_counts")] for r in raw]

        first = optics.acquire(optics.RECIPE, 10, 77, sample_id="blind")
        same = optics.acquire(optics.RECIPE, 10, 77, sample_id="blind")
        different = optics.acquire(optics.RECIPE, 20, 77, sample_id="blind")
        self.assertEqual(len(first), 3)
        self.assertEqual(counts(first), counts(same))
        self.assertNotEqual(counts(first), counts(different))
        for index, reading in enumerate(first, start=1):
            self.assertEqual(reading["replicate"], index)
            self.assertEqual(reading["sample_id"], "blind")
            self.assertEqual(reading["settings"]["wavelength_nm"], 550)
            self.assertEqual(reading["settings"]["path_length_mm"], 10)
            self.assertEqual(reading["instrument_profile"], "osms-sim@1")
            self.assertEqual(reading["source"], "simulated instrument")
            self.assertIn("timestamp", reading)
            self.assertNotIn("concentration", reading)
            self.assertNotIn("seed", reading)

    def test_quality_checks(self):
        counts = dict(dark_counts=10, blank_counts=110, sample_counts=60)
        self.assertAlmostEqual(optics.absorbance(counts), math.log10(2))
        for key, value, message in (("sample_counts", 65535, "Saturated"),
                                    ("sample_counts", 10, "Invalid sample"),
                                    ("blank_counts", 10, "Invalid blank"),
                                    ("blank_counts", float("nan"), "Invalid optical counts")):
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, message):
                optics.absorbance({**counts, key: value})

    def test_calibration_and_held_out_vials(self):
        cal = optics.fit_calibration(optics.RECIPE, 1, noise_counts=0)
        self.assertEqual([s["concentration_mg_l"] for s in cal["standards"]], [3, 5, 10, 15, 20, 24])
        self.assertEqual(len(cal["id"]), 64)
        for concentration in (8, 12, 18, 22, 32):
            raw = optics.acquire(optics.RECIPE, concentration, 2, noise_counts=0)
            result = optics.assess(raw, cal)
            prediction = (statistics.mean(result["absorbances"]) - cal["intercept"]) / cal["slope"]
            self.assertAlmostEqual(prediction, concentration, places=2)
            self.assertEqual(result["in_range"], concentration <= 24)
            self.assertEqual(result["above_range"], concentration > 24)

    def test_independent_checks_in_offline_sandbox(self):
        candidate = """import json, sys
from statistics import mean
s = json.load(sys.stdin)
c = s['calibration']
a = s['absorbances']
valid = all(c['low'] <= reading <= c['high'] for reading in a)
print(json.dumps({'status': 'ok' if valid else 'review', 'sample_id': s['sample_id'],
                  'calibration_id': c['id'], 'concentration_mg_l':
                  (mean(a) - c['intercept']) / c['slope'] if valid else None}))
"""
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'analysis.py'
            source.write_text(candidate)
            self.assertTrue(all(check['pass'] for check in optics.verify_candidate(source)))
            prepared = {c['name']: c['pass'] for c in optics.verify_candidate(source, prepared=True)}
            self.assertTrue(prepared['direct-mean-and-intercept'])
            self.assertFalse(prepared['prepared-2x'])
            self.assertFalse(prepared['prepared-4x'])
            source.write_text(candidate.replace("mean(a)", "a[0]"))
            results = {check['name']: check['pass'] for check in optics.verify_candidate(source)}
            self.assertFalse(results['direct-mean-and-intercept'])
            self.assertTrue(results['above-calibration'])

    def test_preparation_record_and_actual_factor(self):
        prep = {"id": "P-1", "parent_id": "U-1", "sample_ml": 0.25, "final_ml": 1, "unit": "mL"}
        self.assertEqual(optics.validate_preparation("D-1", prep), 4)
        for key, value in (("id", ""), ("parent_id", None), ("parent_id", "D-1"),
                           ("sample_ml", True), ("sample_ml", float("nan")), ("sample_ml", 0),
                           ("final_ml", float("inf")), ("final_ml", 0.25),
                           ("final_ml", -1), ("unit", "L")):
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                optics.validate_preparation("D-1", {**prep, key: value})
        with self.assertRaisesRegex(ValueError, "factor"):
            optics.validate_preparation("D-1", {**prep, "final_ml": 1e308, "sample_ml": 1e-308})
