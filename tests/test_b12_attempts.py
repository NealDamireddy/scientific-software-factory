"""Exercise B12 attempt persistence with the verified direct and prepared releases."""
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from factory import b12_build, optics
from factory.b12_attempts import record_direct_analysis
from factory.archive import validate_archive
from factory.context import ROOT, read_json
from factory.lab import Handler, Lab, ThreadingHTTPServer, save
from factory.sandbox import execute


class B12AttemptTests(unittest.TestCase):
    def setUp(self):
        self.store = Path(self.enterContext(TemporaryDirectory()))
        self.bundle = validate_archive(read_json(ROOT / "public/b12/completed.json"))
        for key in ("direct", "followup"):
            task = self.bundle[key].copy()
            folder = self.store / task["id"]
            folder.mkdir()
            for name, source in self.bundle["sources"][task["id"]]["files"].items():
                (folder / name).write_text(source)
            self.assertEqual(b12_build.revision(folder), task["revision"])
            if key == "followup":
                for field in ("measurement", "result", "score", "replay"):
                    task.pop(field)
            save(folder / "task.json", task)
        self.parent = self.bundle["direct"]["id"]
        self.child = self.bundle["followup"]["id"]
        save(self.store / self.parent / "acquisition.json", self.bundle["initial"])
        self.label = self.bundle["followup"]["score"]["prepared_mg_l"]
        save(self.store / self.parent / "private.json", {"prepared_mg_l": self.label})
        self.lab = Lab(self.store)
        self.addCleanup(lambda: self.lab.close())

    def open_api(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server = server
        server.lab = self.lab
        self.base = f"http://127.0.0.1:{server.server_port}/api/tasks/"
        server.hosts = {f"127.0.0.1:{server.server_port}"}
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

    def reopen(self):
        self.lab.close()
        self.lab = Lab(self.store)
        if hasattr(self, "server"):
            self.server.lab = self.lab

    def request(self, method="GET", suffix="", task_id=None):
        url = self.base + (task_id or self.child) + suffix
        req = Request(url, method=method, data=b"{}" if method == "POST" else None,
                      headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def pending_direct(self, **fields):
        # Stop at the caller boundary owned by WO-19.
        with patch.object(self.lab.pool, "submit"):
            return self.lab.enqueue("Measure the opaque B12 vial", **fields)["id"]

    def test_direct_collection_uses_request_sample_and_legacy_default(self):
        for fields, sample in [({}, "U-01"), ({"sample_id": "Cobalt-09"}, "Cobalt-09")]:
            with self.subTest(sample=sample):
                run = self.pending_direct(**fields)
                with patch("factory.lab.acquire", wraps=optics.acquire) as instrument:
                    acquisition = self.lab.collect(run)
                    self.assertEqual(acquisition["input"]["sample_id"], sample)
                    self.assertTrue(acquisition["finding"]["above_range"])
                    self.assertEqual([r["sample_id"] for r in acquisition["raw"]], [sample] * 3)
                    self.reopen()
                    self.assertEqual(self.lab.collect(run), acquisition)
                    instrument.assert_called_once()
                attempt, = self.lab.task(run)["acquisition_attempts"]
                self.assertEqual(attempt["id"], acquisition["attempt_id"])
                self.assertEqual(attempt["sample_id"], sample)
                self.assertEqual(attempt["raw"], acquisition["raw"])
                self.assertEqual(attempt["calibration_id"], acquisition["calibration"]["id"])

    def test_direct_analysis_callback_records_real_candidate_outcomes(self):
        for should_fail in (False, True):
            sample = "Fault at runtime" if should_fail else "Renamed direct sample"
            with self.subTest(sample=sample):
                run = self.pending_direct(sample_id=sample)
                folder = self.store / run
                release = self.bundle["sources"][self.parent]["files"]
                for name, source in release.items():
                    (folder / name).write_text(source)
                if should_fail:
                    # A candidate can satisfy the public verification contract and still
                    # fail on an unseen input. Verify the deliberately faulty fixture.
                    analysis = folder / "analysis.py"
                    source = analysis.read_text().replace(
                        "data = json.load(sys.stdin)",
                        'data = json.load(sys.stdin)\n    if data["sample_id"] == "Fault at runtime":'
                        '\n        raise RuntimeError("unexpected direct sample")',
                    )
                    self.assertNotEqual(source, release["analysis.py"])
                    analysis.write_text(source)
                    checks = optics.verify_candidate(analysis)
                    self.assertTrue(checks and all(case["pass"] for case in checks), checks)
                revision = b12_build.revision(folder)
                self.lab.update(run, revision=revision, status="verified")
                acquired = self.lab.collect(run)
                payload = json.dumps(acquired["input"]).encode()
                if should_fail:
                    with self.assertRaisesRegex(RuntimeError, "unexpected direct sample") as failure:
                        execute(folder / "analysis.py", payload)
                    self.lab.update(run, status="failed", error=str(failure.exception))
                    record_direct_analysis(self.lab, run, error=failure.exception)
                else:
                    result, _ = execute(folder / "analysis.py", payload)
                    self.lab.update(run, result=result)
                    record_direct_analysis(self.lab, run, revision=revision)
                self.reopen()
                saved = self.lab.task(run)
                attempt, = saved["acquisition_attempts"]
                self.assertEqual(attempt["id"], acquired["attempt_id"])
                self.assertEqual(attempt["raw"], acquired["raw"])
                self.assertEqual(attempt["revision"], revision)
                if should_fail:
                    self.assertEqual(attempt["status"], "rejected")
                    self.assertEqual(attempt["failure"]["field"], "analysis")
                    self.assertIn("unexpected direct sample", attempt["failure"]["reason"])
                    self.assertIsNone(saved.get("result"))
                else:
                    self.assertEqual(attempt["status"], "completed")
                    self.assertEqual(saved["result"]["sample_id"], sample)

    def test_direct_detector_rejection_survives_reopen(self):
        self.open_api()
        run = self.pending_direct(sample_id="Opaque-22")
        raw = optics.acquire(optics.RECIPE, 35, 122, sample_id="Opaque-22")
        raw[1]["sample_counts"] = optics.ADC_MAX
        with patch("factory.lab.acquire", return_value=raw) as instrument:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "[Ss]aturat"):
                    self.lab.collect(run)
                status, task = self.request(task_id=run)
                self.assertEqual(status, 200)
                attempt, = task["acquisition_attempts"]
                self.assertEqual(attempt["raw"], raw)
                self.assertEqual(attempt["status"], "rejected")
                self.assertIn("saturat", attempt["failure"]["reason"].lower())
                self.assertIsNone(task.get("result"))
                self.assertNotIn("prepared_mg_l", json.dumps(task))
                self.reopen()
            instrument.assert_called_once()

    def assert_followup_rejection(self, raw, reason, *, candidate_error=False):
        self.open_api()
        execute = self.enterContext(patch("factory.followup.execute"))
        def read_instrument(*args, **kwargs):
            stored, = read_json(self.store / self.child / "task.json")["acquisition_attempts"]
            self.assertTrue(stored["id"])
            self.assertEqual(stored["sample_id"], kwargs["sample_id"])
            return raw

        instrument = self.enterContext(patch("factory.followup.acquire", side_effect=read_instrument))

        def fail_candidate(*args, **kwargs):
            stored, = read_json(self.store / self.child / "task.json")["acquisition_attempts"]
            self.assertEqual(stored["raw"], raw)
            self.assertTrue(stored["id"])
            raise RuntimeError("fixture candidate failed")

        execute.side_effect = fail_candidate
        status, first = self.request("POST", "/rerun")
        self.assertEqual(status, 200, first)
        attempt, = first["acquisition_attempts"]
        self.assertEqual(attempt["status"], "rejected")
        self.assertTrue(attempt["id"])
        self.assertTrue(attempt["failure"]["field"])
        self.assertIn(reason.lower(), attempt["failure"]["reason"].lower())
        self.assertEqual(attempt["raw"], raw)
        self.assertEqual(attempt["preparation"], self.bundle["followup"]["preparation"])
        self.assertEqual(attempt["sample_id"], self.bundle["followup"]["preparation"]["sample_id"])
        self.assertEqual(attempt["calibration_id"], self.bundle["initial"]["calibration"]["id"])
        self.assertTrue(attempt["settings"])
        self.assertLessEqual(datetime.fromisoformat(attempt["started_at"]),
                             datetime.fromisoformat(attempt["finished_at"]))
        self.assertEqual(execute.call_count, int(candidate_error))
        self.assertEqual(read_json(self.store / self.child / "task.json")["acquisition_attempts"], [attempt])
        self.reopen()
        for method, suffix in [("GET", ""), ("POST", "/rerun")]:
            status, task = self.request(method, suffix)
            self.assertEqual(status, 200, task)
            self.assertEqual(task["acquisition_attempts"], [attempt])
            self.assertIsNone(task.get("measurement"))
            self.assertIsNone(task.get("result"))
            self.assertIsNone(task.get("score"))
            self.assertNotIn("prepared_mg_l", json.dumps(task))
        self.assertEqual(self.request("POST", "/reveal")[0], 400)
        self.assertEqual(self.request("GET", "/evidence")[0], 400)
        instrument.assert_called_once()
        self.assertEqual(execute.call_count, int(candidate_error))
        self.assertEqual(b12_build.revision(self.store / self.child), self.bundle["followup"]["revision"])

    def readings(self):
        prep = self.bundle["followup"]["preparation"]
        return optics.acquire(optics.RECIPE, self.label * prep["sample_ml"] / prep["final_ml"],
                              91, sample_id=prep["sample_id"])

    def test_saturated_followup(self):
        raw = self.readings()
        raw[2]["sample_counts"] = optics.ADC_MAX
        self.assert_followup_rejection(raw, "saturat")

    def test_invalid_blank_counts(self):
        raw = self.readings()
        raw[0]["blank_counts"] = raw[0]["dark_counts"]
        self.assert_followup_rejection(raw, "blank")

    def test_incompatible_blank_settings_with_valid_counts(self):
        raw = self.readings()
        raw[1]["blank_settings"] = {"wavelength_nm": 650, "path_length_mm": 10,
                                   "instrument_profile": "osms-sim@1"}
        self.assert_followup_rejection(raw, "blank")

    def test_candidate_failure_after_saving_raw(self):
        self.assert_followup_rejection(self.readings(), "fixture candidate failed", candidate_error=True)

    def test_interrupted_acquisition_is_not_reissued(self):
        class PowerLoss(BaseException):
            pass

        with patch("factory.followup.acquire", side_effect=PowerLoss) as instrument:
            with self.assertRaises(PowerLoss):
                self.lab.rerun(self.child)
            before, = read_json(self.store / self.child / "task.json")["acquisition_attempts"]
            self.assertTrue(before["id"])
            self.reopen()
            recovered = self.lab.rerun(self.child)
            after, = recovered["acquisition_attempts"]
            self.assertEqual(after["id"], before["id"])
            self.assertEqual(after["status"], "interrupted")
            self.assertIsNone(recovered.get("measurement"))
            self.assertIsNone(recovered.get("result"))
            self.assertIsNone(recovered.get("score"))
            instrument.assert_called_once()

    def test_explicit_retry_is_distinct_and_repeatable(self):
        raw = self.readings()
        raw[0]["sample_counts"] = optics.ADC_MAX
        with patch("factory.followup.acquire", return_value=raw):
            first, = self.lab.rerun(self.child)["acquisition_attempts"]
        self.reopen()
        with patch("factory.followup.acquire", wraps=optics.acquire) as instrument:
            second = self.lab.rerun(self.child, retry_of=first["id"])
            old, new = second["acquisition_attempts"]
            self.assertEqual(old, first)
            self.assertNotEqual(new["id"], first["id"])
            self.assertEqual(new["status"], "completed")
            self.assertEqual(second["result"]["status"], "ok")
            self.reopen()
            for args in ({"retry_of": first["id"]}, {}):
                self.assertEqual(self.lab.rerun(self.child, **args)["acquisition_attempts"], [first, new])
            instrument.assert_called_once()

    def test_earlier_retry_key_selects_its_original_rejected_successor(self):
        raw = self.readings()
        raw[0]["sample_counts"] = optics.ADC_MAX
        with patch("factory.followup.acquire", return_value=raw) as instrument:
            first = self.lab.rerun(self.child)["acquisition_attempt_id"]
            second = self.lab.rerun(self.child, retry_of=first)["acquisition_attempt_id"]
            self.assertEqual(instrument.call_count, 2)
        last = self.lab.rerun(self.child, retry_of=second)
        self.lab.reveal(self.child)
        self.reopen()
        with patch("factory.followup.acquire") as instrument:
            previous = self.lab.rerun(self.child, retry_of=first)
            instrument.assert_not_called()
        self.assertEqual(previous["acquisition_attempt_id"], second)
        self.assertEqual(previous["acquisition_status"], "rejected")
        self.assertEqual(previous["acquisition_attempts"], last["acquisition_attempts"])
        for key in ("measurement", "result", "score", "replay"):
            self.assertNotIn(key, previous)
        self.assertEqual(self.lab.task(self.child)["result"], last["result"])

    def test_successful_triplicate_remains_replayable_and_revealable(self):
        self.open_api()
        self.assertEqual(self.request("POST", "/reveal")[0], 400)
        status, task = self.request("POST", "/rerun")
        self.assertEqual(status, 200, task)
        attempt, = task["acquisition_attempts"]
        measurement = task["measurement"]
        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(measurement["attempt_id"], attempt["id"])
        self.assertEqual(attempt["raw"], measurement["raw"])
        self.assertEqual([r["replicate"] for r in measurement["raw"]], [1, 2, 3])
        self.assertEqual(measurement["calibration_id"], self.bundle["initial"]["calibration"]["id"])
        self.assertEqual(task["result"]["status"], "ok")
        self.assertAlmostEqual(task["result"]["concentration_mg_l"], self.label, delta=0.3)
        self.assertIsNone(task.get("score"))
        status, exported = self.request("GET", "/evidence")
        self.assertEqual(status, 200, exported)
        self.assertEqual(exported["followup"]["acquisition_attempts"], [attempt])
        self.assertEqual(exported["followup"]["measurement"], measurement)
        self.assertTrue(exported["environment"]["dependency_lock"])
        self.assertTrue(exported["checks"])
        self.assertTrue(exported["scientific_review"])
        self.assertEqual(self.request("POST", "/replay")[0], 200)
        self.assertEqual(self.request("POST", "/reveal")[1]["score"]["prepared_mg_l"], self.label)

    def assert_bad_preparation(self, change, reason):
        prep = {**self.bundle["followup"]["preparation"], **change}
        self.lab.update(self.child, preparation=prep)
        with patch("factory.followup.acquire") as instrument:
            failed = self.lab.rerun(self.child)
            attempt, = failed["acquisition_attempts"]
            self.assertEqual(attempt["preparation"], prep)
            self.assertEqual(attempt["status"], "rejected")
            self.assertIn(reason, attempt["failure"]["reason"].lower())
            self.assertFalse(attempt.get("raw"))
            self.assertIsNone(failed.get("measurement"))
            self.assertIsNone(failed.get("result"))
            self.reopen()
            self.assertEqual(self.lab.rerun(self.child)["acquisition_attempts"], [attempt])
            instrument.assert_not_called()

    def test_invalid_persisted_preparation_volume(self):
        self.assert_bad_preparation({"sample_ml": 0}, "sample_ml")

    def test_invalid_persisted_preparation_unit(self):
        self.assert_bad_preparation({"unit": "L"}, "unit")

    def test_invalid_persisted_preparation_lineage(self):
        self.assert_bad_preparation({"parent_id": "unknown parent"}, "parent")

    def test_prerequisites_and_verified_source_checked_before_reading(self):
        record = self.bundle["followup"]
        with patch("factory.followup.acquire") as instrument:
            for field, value in [("status", "verifying"), ("preparation", None), ("approval", None)]:
                with self.subTest(field=field):
                    self.lab.update(self.child, **{field: value})
                    with self.assertRaises(ValueError):
                        self.lab.rerun(self.child)
                    self.lab.update(self.child, **{field: record[field]})
            (self.store / self.child / "analysis.py").write_text("# altered after verification")
            task = self.lab.rerun(self.child)
            failed, = task["acquisition_attempts"]
            self.assertEqual(failed["status"], "rejected")
            self.assertEqual(failed["failure"]["field"], "preflight")
            self.assertIn("digest", failed["failure"]["reason"].lower())
            instrument.assert_not_called()
            self.assertIsNone(self.lab.task(self.child).get("measurement"))

    def test_legacy_completed_measurement_is_returned_without_new_readings(self):
        save(self.store / self.child / "task.json", self.bundle["followup"])
        with patch("factory.followup.acquire") as instrument:
            self.assertEqual(self.lab.rerun(self.child), self.bundle["followup"])
            instrument.assert_not_called()
