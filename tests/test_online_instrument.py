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
