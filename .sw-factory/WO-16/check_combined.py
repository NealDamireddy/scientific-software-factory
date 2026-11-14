"""Run from the combined WO-16/17/19 checkout with loopback and the candidate sandbox.

    python3 .sw-factory/WO-16/check_combined.py

Requires the merged application and the WO-19 HTTP fixture. A missing lane exits nonzero.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
missing = [name for name in ("factory/b12_attempts.py", "factory/archive_measurements.py",
                             "factory/b12_reuse.py", "tests/test_b12_reuse_requests.py")
           if not (ROOT / name).is_file()]
if missing:
    sys.exit("Combined acceptance unavailable in this checkout. Missing " + ", ".join(missing))

from factory import b12_build, optics
from factory.context import read_json
from factory.lab import Lab
from tests import test_b12_reuse_requests as reuse


class CombinedAcceptance(unittest.TestCase):
    def setUp(self):
        # Reuse only the temporary store, seed, HTTP transport and queue barrier.
        self.fixture = reuse.RequestReuseTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def submit(self, request, sample):
        queued = request("/api/tasks", {"brief": "Measure B12 at 550 nm", "sample_id": sample})
        self.fixture.wait_for_task(queued["id"])
        return request("/api/tasks/" + queued["id"])

    def test_direct_analysis_through_fresh_and_reused_dispatch(self):
        bundle = self.fixture.bundle
        files = bundle["sources"][bundle["direct"]["id"]]["files"]
        # Pass the actual verifier, but fail inside the real candidate runner for two unseen vials.
        parse = "    data = json.load(sys.stdin)"
        self.assertEqual(files["analysis.py"].count(parse), 1)
        code = files["analysis.py"].replace(parse, parse + '\n    if data["sample_id"].startswith("Fault-"):'
                                             '\n        raise RuntimeError("fixture unseen vial failure")')
        candidate = {"source": code, "recipe": json.loads(files["recipe.json"]),
                     "views": json.loads(files["views.json"])}
        with self.fixture.presenter() as request, patch.object(
                b12_build, "invoke_worker", return_value=(candidate, {"method": "fixture"})) as worker:
            for sample, mode in (("Fault-fresh", "fresh generation"), ("Fresh-success", "fresh generation"),
                                 ("Reused-success", "verified source reuse"), ("Fault-reuse", "verified source reuse")):
                with self.subTest(sample=sample):
                    task = self.submit(request, sample)
                    self.assertEqual(task["mode"], mode)
                    attempt, = task["acquisition_attempts"]
                    self.assertEqual([r["sample_id"] for r in attempt["raw"]], [sample] * 3)
                    self.assertEqual(attempt["revision"], task["revision"])
                    self.assertEqual(attempt["calibration_id"], read_json(
                        self.fixture.store / task["id"] / "acquisition.json")["calibration"]["id"])
                    if sample.startswith("Fault-"):
                        self.assertEqual((task["status"], attempt["status"]), ("failed", "rejected"))
                        self.assertEqual(attempt["failure"]["field"], "analysis")
                        self.assertIn("fixture unseen vial failure", attempt["failure"]["reason"])
                        self.assertIsNone(task.get("result"))
                    else:
                        self.assertEqual((task["status"], attempt["status"]), ("verified", "completed"))
                        self.assertEqual(task["result"]["sample_id"], sample)
            self.assertEqual(worker.call_count, 2)

    def test_renamed_fourfold_saturation_reopen_retry_and_archive(self):
        fixture = self.fixture
        source = fixture.seed_live("direct")
        prepared_source = fixture.seed_live("followup")
        calls = []
        vial = "Renamed lot 16"
        prep = dict(parent_id=vial, sample_id=vial + "-4", sample_ml=0.75, final_ml=3.0, unit="mL")

        def instrument(*args, **kwargs):
            raw = optics.acquire(*args, **kwargs)
            if not calls:
                raw[1]["sample_counts"] = optics.ADC_MAX
            calls.append(deepcopy(raw))
            return raw

        with patch.object(b12_build, "invoke_worker", side_effect=AssertionError("unexpected coding worker")) as worker, \
                patch("factory.followup.acquire", side_effect=instrument):
            with fixture.presenter() as request:
                direct = self.submit(request, vial)
                fixture.assert_reused(direct, source)
                self.assertTrue(direct["finding"]["above_range"])
                self.assertEqual(direct["result"]["sample_id"], vial)
                self.assertIsNone(direct["result"]["concentration_mg_l"])
                self.assertEqual(direct["acquisition_status"], "completed")
                calibration = direct["result"]["calibration_id"]
                child = request(f"/api/tasks/{direct['id']}/approve", {"factor": 4})
                child_id = child["id"]
                prefix = "/api/tasks/" + child_id
                fixture.assert_reused(fixture.wait_for_task(child_id), prepared_source)
                self.assertEqual(len({direct["id"], child_id, source["id"], prepared_source["id"]}), 4)
                self.assertEqual(child["approval"]["origin"], direct["id"])
                self.assertEqual(child["approval"]["evidence"]["readings"], direct["finding"]["absorbances"])
                self.assertEqual(child["approval"]["factor"], 4)
                recorded = request(prefix + "/prepare", prep)["preparation"]
                self.assertEqual({key: recorded[key] for key in prep}, prep)
                first = request(prefix + "/rerun", {})
                attempt, = first["acquisition_attempts"]
                self.assertEqual(attempt["status"], "rejected")
                self.assertIn("saturat", attempt["failure"]["reason"].lower())
                self.assertEqual(attempt["raw"], calls[0])
                self.assertEqual(len(attempt["raw"]), 3)
                self.assertEqual(attempt["revision"], prepared_source["revision"])
                self.assertEqual(attempt["preparation"], recorded)
                self.assertEqual(attempt["calibration_id"], calibration)
                self.assertEqual(read_json(fixture.store / child_id / "task.json")["acquisition_attempts"], [attempt])

            fixture.lab.close()
            fixture.lab = Lab(fixture.store)
            self.addCleanup(fixture.lab.close)
            with fixture.presenter() as request:
                for saved in (request(prefix), request(prefix + "/rerun", {})):
                    self.assertEqual(saved["acquisition_attempts"], [attempt])
                    self.assertEqual(saved["acquisition_attempt_id"], attempt["id"])
                    for key in ("result", "measurement", "score"):
                        self.assertIsNone(saved.get(key))
                    self.assertNotIn("prepared_mg_l", json.dumps(saved))
                self.assertEqual(len(calls), 1)
                with self.assertRaises(HTTPError) as reveal:
                    request(prefix + "/reveal", {})
                self.assertEqual(reveal.exception.code, 400)
                retry = {"retry_of": attempt["id"]}
                recovered = request(prefix + "/rerun", retry)
                old, current = recovered["acquisition_attempts"]
                self.assertEqual(old, attempt)
                self.assertNotEqual(current["id"], old["id"])
                self.assertEqual((current["retry_of"], current["status"]), (old["id"], "completed"))
                self.assertEqual(recovered["measurement"]["raw"], calls[1])
                self.assertEqual(recovered["result"]["status"], "ok")
                self.assertEqual(request(prefix + "/rerun", retry)["acquisition_attempts"], [old, current])
                self.assertEqual(len(calls), 2)
                package = request(prefix + "/evidence")
            worker.assert_not_called()

        # Verify the real export first. Then present the rejected attempt as having
        # produced the later successful estimate; only the follow-up evidence changes.
        store = fixture.store / "archive-only"
        fixture.lab = Lab(store, archive=package, allow_generation=False)
        try:
            with fixture.presenter() as request:
                self.assertTrue(request(prefix)["archived"])
        finally:
            fixture.lab.close()
        forged = deepcopy(package)
        child = forged["followup"]
        child.update(acquisition_attempts=[attempt], acquisition_attempt_id=attempt["id"],
                     acquisition_status="rejected")
        child["measurement"].update(raw=attempt["raw"], attempt_id=attempt["id"])
        with self.assertRaisesRegex(ValueError, "(?i)followup.*attempt.*status"):
            Lab(store, archive=forged, allow_generation=False).close()
        self.assertFalse(store.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
