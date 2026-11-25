"""Retain direct calibration observations and reconcile acquired counts across restarts."""
import json
from unittest.mock import patch

from factory.assays.b12 import b12_build, optics
from factory.context import read_json
from factory.assays.b12.lab import Lab
from tests.test_b12_attempts import B12AttemptFixture


class CalibrationCheckpointTests(B12AttemptFixture):
    def test_saturated_first_standard(self):
        self.check_standard_rejection(0, "saturated")

    def test_invalid_first_blank(self):
        self.check_standard_rejection(0, "blank")

    def test_later_standard_retains_all_preceding_readings(self):
        self.check_standard_rejection(2, "saturated")

    def check_standard_rejection(self, bad_index, fault):
        self.open_api()
        run = self.pending_direct(sample_id="calibration-gate")
        observed = []
        acquire = optics.acquire

        def instrument_read(*args, **kwargs):
            concentration = args[1]
            raw = acquire(*args, **kwargs)
            if len(observed) == bad_index:
                failed = raw[1]
                if fault == "saturated":
                    failed["sample_counts"] = optics.ADC_MAX
                else:
                    failed["blank_counts"] = failed["dark_counts"]
            observed.append({"concentration_mg_l": concentration, "raw": raw})
            return raw

        with patch("factory.assays.b12.optics.acquire", side_effect=instrument_read) as standards, \
                patch("factory.assays.b12.lab.acquire") as vial:
            with self.assertRaisesRegex(ValueError, f"(?i){fault}"):
                self.lab.collect(run)
            status, body = self.request(task_id=run)
            self.assertEqual(status, 200)
            attempt, = body["acquisition_attempts"]
            self.assertEqual(attempt["status"], "rejected")
            self.assertEqual(attempt["calibration_standards"], observed)
            self.assertEqual([s["concentration_mg_l"] for s in observed],
                             list(optics.STANDARDS_MG_L[:bad_index + 1]))
            self.assertEqual(attempt["failure"]["field"], "calibration")
            self.assertIn(fault, attempt["failure"]["reason"].lower())
            self.assertFalse(attempt["raw"])
            self.assertIsNone(attempt["calibration_id"])
            self.assertEqual(read_json(self.store / run / "task.json")["acquisition_attempts"], [attempt])
            self.reopen()
            with self.assertRaisesRegex(ValueError, f"(?i){fault}"):
                self.lab.collect(run)
            status, body = self.request(task_id=run)
            self.assertEqual(status, 200)
            self.assertEqual(body["acquisition_attempts"], [attempt])
            for field in ("result", "measurement", "score"):
                self.assertIsNone(body.get(field))
            self.assertEqual(self.request("POST", "/reveal", task_id=run)[0], 400)
            self.assertEqual(standards.call_count, bad_index + 1)
            vial.assert_not_called()

    def test_fresh_pi_request_exposes_failed_standard_after_restart(self):
        released = self.bundle["sources"][self.parent]["files"]
        candidate = {"source": released["analysis.py"], "recipe": json.loads(released["recipe.json"]),
                     "views": json.loads(released["views.json"])}
        # Exercise generation in an empty live store using a previously verified
        # candidate as the bounded coding-worker response.
        self.lab.close()
        self.store = self.store / "fresh"
        self.lab = Lab(self.store)
        self.open_api()
        acquire = optics.acquire
        observed = []

        def saturate_standard(*args, **kwargs):
            raw = acquire(*args, **kwargs)
            raw[0]["sample_counts"] = optics.ADC_MAX
            observed.extend(raw)
            return raw

        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(candidate, {"method": "fixture"})) as worker, \
                patch("factory.assays.b12.optics.acquire", side_effect=saturate_standard) as standards, \
                patch("factory.assays.b12.lab.acquire") as vial:
            status, ticket = self.request("POST", task_id="", body={"brief": "Measure B12 at 550 nm"})
            self.assertEqual(status, 202, ticket)
            self.assertEqual(self.request(task_id=ticket["id"])[0], 200)
            self.lab.pool.shutdown()
            status, task = self.request(task_id=ticket["id"])
            self.assertEqual(status, 200)
            self.assertEqual(task["status"], "failed")
            self.assertEqual(task["revision"], self.bundle["direct"]["revision"])
            self.assertIn("saturat", task["error"].lower())
            self.assertIsNone(task.get("result"))
            self.assertIsNone(task.get("score"))
            attempt, = task["acquisition_attempts"]
            self.assertEqual(attempt["status"], "rejected")
            self.assertEqual(attempt["calibration_standards"],
                             [{"concentration_mg_l": optics.STANDARDS_MG_L[0], "raw": observed}])
            self.assertEqual(read_json(self.store / ticket["id"] / "task.json")["acquisition_attempts"], [attempt])
            self.reopen()
            self.assertEqual(self.request(task_id=ticket["id"]), (200, task))
            with self.assertRaisesRegex(ValueError, "Saturated"):
                self.lab.collect(ticket["id"])
            standards.assert_called_once()
            vial.assert_not_called()
            worker.assert_called_once()

    def test_checkpoint_preserves_frozen_fit_and_digest(self):
        seed = 9321
        captured = []
        acquire = optics.acquire

        def capture(*args, **kwargs):
            raw = acquire(*args, **kwargs)
            captured.append(raw)
            return raw

        with patch("factory.assays.b12.optics.acquire", side_effect=capture) as baseline:
            original = optics.fit_calibration(optics.RECIPE, seed)
        checkpoints = []
        with patch("factory.assays.b12.optics.acquire", side_effect=captured) as replay:
            journaled = optics.fit_calibration(
                optics.RECIPE, seed, checkpoint_standard=lambda concentration, raw:
                checkpoints.append((concentration, raw)))
        self.assertEqual(replay.call_args_list, baseline.call_args_list)
        self.assertEqual(checkpoints, list(zip(optics.STANDARDS_MG_L, captured)))
        self.assertEqual(journaled, original)
        self.assertEqual(journaled["id"], optics.calibration_digest(original))

    def test_successful_fit_uses_the_journaled_standard_triplicates(self):
        self.open_api()
        run = self.pending_direct()
        absorbance = optics.absorbance

        def check_saved_then_assess(record):
            if record["sample_id"].startswith("std-"):
                task = read_json(self.store / run / "task.json")
                attempt, = task["acquisition_attempts"]
                evidence = attempt["calibration_standards"][-1]
                self.assertEqual(len(evidence["raw"]), 3)
                self.assertEqual(evidence["raw"][record["replicate"] - 1], record)
            return absorbance(record)

        with patch("factory.assays.b12.optics.absorbance", side_effect=check_saved_then_assess):
            acquired = self.lab.collect(run)
        frozen = acquired["calibration"]
        self.assertEqual(frozen["id"], optics.calibration_digest(frozen))
        self.assertGreater(frozen["slope"], 0)
        expected = [{"concentration_mg_l": standard["concentration_mg_l"], "raw": standard["raw"]}
                    for standard in frozen["standards"]]
        self.assertEqual([s["concentration_mg_l"] for s in expected], list(optics.STANDARDS_MG_L))
        self.reopen()
        status, task = self.request(task_id=run)
        self.assertEqual(status, 200)
        attempt, = task["acquisition_attempts"]
        self.assertEqual(attempt["calibration_standards"], expected)
        self.assertEqual(attempt["calibration_id"], frozen["id"])
        with patch("factory.assays.b12.optics.acquire") as standards, patch("factory.assays.b12.lab.acquire") as vial:
            self.assertEqual(self.lab.collect(run), acquired)
            standards.assert_not_called()
            vial.assert_not_called()


class AnalysisCheckpointTests(B12AttemptFixture):
    def fail_on_live_sample(self, response):
        # Public verification cases still exercise the released analysis normally.
        folder = self.store / self.child
        source = folder / "analysis.py"
        original = source.read_text()
        sample = self.bundle["followup"]["preparation"]["sample_id"]
        output = "    json.dump(result, sys.stdout, allow_nan=False)"
        self.assertIn(output, original)
        source.write_text(original.replace(output, f"    if data['sample_id'] == {sample!r}:\n"
                                           f"        {response}\n        return\n" + output))
        checks = optics.verify_candidate(source, prepared=True)
        self.assertTrue(checks and all(case["pass"] for case in checks), checks)
        self.lab.update(self.child, revision=b12_build.revision(folder), checks=checks)

    def check_rejected_candidate(self, reason):
        self.open_api()
        with patch("factory.assays.b12.followup.acquire", wraps=optics.acquire) as instrument:
            status, first = self.request("POST", "/rerun")
            self.assertEqual(status, 200, first)
            saved, = read_json(self.store / self.child / "task.json")["acquisition_attempts"]
            self.assertEqual(saved["status"], "rejected")
            self.assertEqual(saved["failure"]["field"], "analysis")
            self.assertIn(reason.lower(), saved["failure"]["reason"].lower())
            self.assertEqual(saved["raw"], first["acquisition_attempts"][0]["raw"])
            self.assertEqual(len(saved["raw"]), 3)
            self.assertTrue(saved["finding"]["in_range"])
            self.assertEqual(saved["calibration_id"], self.bundle["initial"]["calibration"]["id"])
            self.reopen()
            for method, path in [("GET", ""), ("POST", "/rerun")]:
                status, body = self.request(method, path)
                self.assertEqual(status, 200)
                self.assertEqual(body["acquisition_attempts"], [saved])
                for field in ("measurement", "result", "score"):
                    self.assertIsNone(body.get(field))
                self.assertNotIn("prepared_mg_l", json.dumps(body))
            instrument.assert_called_once()
            self.assertEqual(self.request("POST", "/reveal")[0], 400)
            self.assertEqual(self.request("GET", "/evidence")[0], 400)

    def test_invalid_candidate_json_is_retained_as_analysis_rejection(self):
        self.fail_on_live_sample('print("malformed output from candidate")')
        self.check_rejected_candidate("expecting value")

    def test_nonfinite_extra_candidate_field_is_retained_as_analysis_rejection(self):
        # The primary estimate remains correct. Reject the invalid extension before
        # the atomic JSON writer, where this used to leave an acquired attempt.
        self.fail_on_live_sample("json.dump(dict(result, extra=float('nan')), sys.stdout)")
        self.check_rejected_candidate("JSON compliant")

    def test_reopen_resumes_analysis_from_acquired_raw_counts(self):
        class ProcessStopped(BaseException):
            pass

        self.open_api()
        with patch("factory.assays.b12.followup.acquire", wraps=optics.acquire) as instrument:
            with patch("factory.assays.b12.followup.execute", side_effect=ProcessStopped), self.assertRaises(ProcessStopped):
                self.lab.rerun(self.child)
            snapshot = read_json(self.store / self.child / "task.json")
            checkpoint, = snapshot["acquisition_attempts"]
            self.assertEqual(checkpoint["status"], "acquired")
            self.assertEqual(len(checkpoint["raw"]), 3)
            self.reopen()
            status, recovered = self.request()
            self.assertEqual(status, 200)
            self.assertEqual(recovered["acquisition_attempts"], [checkpoint])
            for field in ("measurement", "result", "score"):
                self.assertIsNone(recovered.get(field))
            self.assertEqual(self.request("POST", "/reveal")[0], 400)
            status, completed = self.request("POST", "/rerun")
            self.assertEqual(status, 200, completed)
            attempt, = completed["acquisition_attempts"]
            self.assertEqual(attempt["status"], "completed")
            measurement = completed["measurement"]
            for key in ("raw", "calibration_id", "preparation", "sample_id", "acquired_at"):
                self.assertEqual(attempt[key], checkpoint[key])
            self.assertEqual(measurement["raw"], checkpoint["raw"])
            self.assertEqual(measurement["attempt_id"], checkpoint["id"])
            self.assertEqual(completed["result"]["status"], "ok")
            instrument.assert_called_once()
