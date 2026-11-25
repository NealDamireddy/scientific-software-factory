import unittest

from api.instrument import BUNDLE, measure


class OnlineInstrumentTests(unittest.TestCase):
    def submit(self, release, **overrides):
        app = BUNDLE[release]
        request = {"revision": app["revision"], "files": BUNDLE["sources"][app["id"]]["files"], "vial": "B"}
        return measure({**request, **overrides})

    def test_direct_and_prepared_acquisition(self):
        direct = self.submit("direct")
        prepared = self.submit("followup")
        self.assertNotEqual(direct["run_id"], prepared["run_id"])
        for receipt in (direct, prepared):
            self.assertEqual(len(receipt["raw"]), 3)
            self.assertNotIn("concentration_mg_l", receipt["analysis_input"])
        raw, diluted = direct["analysis_input"], prepared["analysis_input"]
        self.assertGreater(min(raw["absorbances"]), raw["calibration"]["high"])
        self.assertLess(max(diluted["absorbances"]), diluted["calibration"]["high"])
        self.assertEqual(diluted["preparation"]["parent_id"], raw["sample_id"])

    def test_rejects_unreleased_application(self):
        with self.assertRaises(ValueError):
            self.submit("direct", files={"analysis.py": "print(42)"})


class HostedReferenceTests(unittest.TestCase):
    """The hosted demo recomputes every result and refuses one that disagrees."""

    def setUp(self):
        from api.instrument import CALIBRATION
        self.calibration = CALIBRATION
        self.spec = {
            "application_name": "B12 check", "sample": "Vial A", "analyte": "vitamin B12",
            "wavelength_nm": 550, "readings": 3, "light_path_mm": 10,
            "standards_mg_l": [row["concentration_mg_l"] for row in CALIBRATION["standards"]],
            "output": "concentration in mg/L; withhold outside calibration",
        }

    def test_wrong_formulas_fail_the_hosted_calibration_checks(self):
        from factory.assays.b12.hosted_assay import compile_assay
        release = compile_assay(self.spec, "(signal - intercept) / slope", self.calibration)
        self.assertIn("direct-steep-calibration", release["checks"])
        # Each of these passed the old checks, whose one calibration had intercept = 2 * slope.
        for expression in ("(signal - intercept) / (intercept - slope)", "(signal - slope - slope) / slope",
                           "(signal - slope - slope) / (intercept - slope)"):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, "calibration checks"):
                compile_assay(self.spec, expression, self.calibration)

    def test_generated_run_carries_the_host_calculation(self):
        from factory.assays.b12.hosted_assay import compile_assay, evaluate
        release = compile_assay(self.spec, "(signal - intercept) / slope", self.calibration)
        receipt = measure({**release, "vial": "A"})
        reference = receipt["reference"]
        readings = receipt["analysis_input"]["absorbances"]
        expected = (sum(readings) / 3 - self.calibration["intercept"]) / self.calibration["slope"]
        self.assertEqual(reference["status"], "ok")
        self.assertAlmostEqual(reference["concentration_mg_l"], expected, places=9)
        self.assertAlmostEqual(reference["concentration_mg_l"], 12, delta=0.5)
        self.assertEqual(evaluate(release, receipt["analysis_input"])["concentration_mg_l"],
                         reference["concentration_mg_l"])

    def test_disagreeing_output_is_refused(self):
        from factory.assays.b12.hosted_assay import check_against_reference, reference_result
        analysis_input = {"sample_id": "vial-A", "preparation": None, "absorbances": [0.1, 0.11, 0.12],
                          "calibration": {k: self.calibration[k] for k in ("id", "slope", "intercept", "low", "high")}}
        reference = reference_result(analysis_input)
        self.assertIs(check_against_reference(dict(reference), reference)["status"], "ok")
        for change in ({"concentration_mg_l": -12.1}, {"concentration_mg_l": None}, {"status": "review"},
                       {"calibration_id": "other"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "disagrees"):
                check_against_reference({**reference, **change}, reference)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            check_against_reference(None, reference)

    def test_released_apps_agree_with_the_reference_in_the_sandbox(self):
        import json
        import tempfile
        from pathlib import Path
        from factory.assays.b12.hosted_assay import check_against_reference
        from factory.software.sandbox import execute
        for role, vial in (("direct", "A"), ("direct", "B"), ("followup", "B")):
            with self.subTest(role=role, vial=vial), tempfile.TemporaryDirectory() as folder:
                app = BUNDLE[role]
                files = BUNDLE["sources"][app["id"]]["files"]
                receipt = measure({"revision": app["revision"], "files": files, "vial": vial})
                source = Path(folder) / "analysis.py"
                source.write_text(files["analysis.py"])
                output, _ = execute(source, json.dumps(receipt["analysis_input"]).encode())
                check_against_reference(output, receipt["reference"])
