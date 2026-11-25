"""The hosted presenter refuses wrong model expressions and says so."""
import io
import json
import os
import unittest
from unittest.mock import patch

from api.instrument import CALIBRATION
from api.presenter import generate


SPEC = {
    "application_name": "B12 check", "sample": "Vial A", "analyte": "vitamin B12",
    "wavelength_nm": 550, "readings": 3, "light_path_mm": 10,
    "standards_mg_l": [row["concentration_mg_l"] for row in CALIBRATION["standards"]],
    "output": "concentration in mg/L; withhold outside calibration",
}


def post(model_expression):
    handler = object.__new__(generate.handler)
    body = json.dumps(SPEC).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    replies = []
    handler.reply = lambda status, data: replies.append((status, data))
    answer = io.BytesIO(json.dumps({"choices": [{"message": {"content": model_expression}}]}).encode())
    with patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "test"}), \
            patch.object(generate, "urlopen", return_value=answer), patch("builtins.print"):
        handler.do_POST()
    return replies[0]


class PresenterGenerateTests(unittest.TestCase):
    def test_model_expression_that_passes_is_used(self):
        status, release = post("(signal - intercept) / slope")
        self.assertEqual(status, 200)
        self.assertIn("openai/", release["worker"]["model"])
        self.assertNotIn("rejected_model_expression", release["worker"])

    def test_wrong_model_expression_is_refused_and_recorded(self):
        # Passed the old checks, whose one calibration had intercept = 2 * slope.
        status, release = post("(signal - intercept) / (intercept - slope)")
        self.assertEqual(status, 200)
        self.assertEqual(release["worker"]["model"], "EVOLVE protocol compiler")
        rejected = release["worker"]["rejected_model_expression"]
        self.assertIn("calibration checks", rejected["reason"])
        self.assertEqual(rejected["expression"], "(signal - intercept) / (intercept - slope)")
        self.assertEqual(release["expression"], "(signal - intercept) / slope")


if __name__ == "__main__":
    unittest.main()
