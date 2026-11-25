"""B12 release reuse through the presenter request and acquisition interfaces."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from tests.b12_release_fixtures import verified_task

from factory.assays.b12 import b12_build
from factory.context import ROOT, read_json
from factory.assays.b12.b12_verification import verification_receipt
from factory.assays.b12.lab import Handler, Lab, ThreadingHTTPServer, save


class RequestReuseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Path(directory.name)
        self.bundle = read_json(ROOT / "public/b12/completed.json")
        self.lab = Lab(self.store)
        self.addCleanup(self.lab.close)

    def seed_live(self, kind):
        """Explicitly install a revision-bound verified release in this test's live store."""
        task = verified_task(self.bundle, kind)
        folder = self.store / task["id"]
        folder.mkdir()
        save(folder / "task.json", task)
        files = self.bundle["sources"][task["id"]]["files"]
        for name, source in files.items():
            (folder / name).write_text(source)
        if kind == "direct":
            save(folder / "acquisition.json", self.bundle["initial"])
        self.assertEqual(b12_build.revision(folder), task["revision"])
        return task

    def wait_for_task(self, task_id):
        # A barrier in the FIFO single-worker executor waits for all prior requests.
        self.lab.pool.submit(lambda: None).result(timeout=45)
        return self.lab.task(task_id)

    def collect_requested_sample(self, task_id):
        # WO-16 owns collect. Model its caller contract without another acquisition
        # implementation: use one real collection and annotate its requested vial.
        task = self.lab.task(task_id)
        measurement = Lab.collect(self.lab, task_id)
        measurement["input"]["sample_id"] = task["sample_id"]
        for reading in measurement["raw"]:
            reading["sample_id"] = task["sample_id"]
        save(self.lab.path(task_id) / "acquisition.json", measurement)
        return measurement

    @contextmanager
    def presenter(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            host = f"127.0.0.1:{server.server_port}"
            server.hosts = {host}
            server.lab = self.lab
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            def request(path, body=None):
                payload = json.dumps(body).encode() if body is not None else None
                req = Request("http://" + host + path, data=payload,
                              headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=15) as response:
                    return json.load(response)

            try:
                yield request
            finally:
                server.shutdown()
                thread.join()

    def assert_reused(self, task, source):
        self.assertEqual(task["status"], "verified", task.get("error"))
        self.assertNotEqual(task["id"], source["id"])
        self.assertEqual(task["mode"], "verified source reuse")
        self.assertEqual(task["origin_task_id"], source["id"])
        self.assertEqual(task["revision"], source["revision"])
        self.assertEqual(task["worker"], source["worker"])
        self.assertEqual(task["checks"], source["checks"])
        self.assertEqual(task["verification"], source["verification"])
        folder = self.lab.path(task["id"])
        for name in b12_build.FILES:
            self.assertEqual((folder / name).read_bytes(), (self.store / source["id"] / name).read_bytes())

    def test_http_renamed_sample_and_independent_preparations_reuse_original_releases(self):
        original = self.seed_live("direct")
        prepared = self.seed_live("followup")
        before = {t["id"]: (self.store / t["id"] / "task.json").read_bytes()
                  for t in (original, prepared)}
        observed = []

        def collect(task_id):
            task = self.lab.task(task_id)
            observed.append((task_id, task["sample_id"], task["revision"]))
            return self.collect_requested_sample(task_id)

        with self.presenter() as request, patch.object(self.lab, "collect", side_effect=collect), \
                patch("factory.assays.b12.b12_build.invoke_worker", side_effect=AssertionError("unexpected generation")) as worker:
            vial = "Assay lot C"
            queued = request("/api/tasks", {"brief": "Measure B12 at 550 nm", "sample_id": vial})
            direct = self.wait_for_task(queued["id"])
            self.assert_reused(direct, original)
            self.assertEqual(observed, [(direct["id"], vial, original["revision"])])
            self.assertEqual(direct["result"]["sample_id"], vial)
            self.assertTrue(direct["finding"]["above_range"])
            self.assertIsNone(direct["result"]["concentration_mg_l"])
            approval_path = f"/api/tasks/{direct['id']}/approve"
            ids = {original["id"], prepared["id"], direct["id"]}
            approvals = {}
            for factor in (2, 4):
                with self.subTest(factor=factor):
                    child = request(approval_path, {"factor": factor})
                    self.assertNotIn(child["id"], ids)
                    ids.add(child["id"])
                    approval = child["approval"]
                    self.assertEqual(approval["factor"], factor)
                    self.assertEqual(approval["origin"], direct["id"])
                    self.assertEqual(approval["parent_sample_id"], vial)
                    self.assertEqual(approval["evidence"]["calibration_id"], direct["result"]["calibration_id"])
                    self.assertEqual(approval["evidence"]["readings"], direct["finding"]["absorbances"])
                    self.assertEqual(approval["evidence"]["upper_standard"], direct["proposal"]["upper_standard"])
                    approvals[child["id"]] = approval
                    prefix = f"/api/tasks/{child['id']}"
                    preparation = {"sample_id": f"{vial}-{factor}", "parent_id": vial,
                                   "sample_ml": 0.75, "final_ml": 0.75 * factor, "unit": "mL"}
                    request(prefix + "/prepare", preparation)
                    self.assert_reused(self.wait_for_task(child["id"]), prepared)
                    measured = request(prefix + "/rerun", {})
                    result = measured["result"]
                    self.assertEqual(result["sample_id"], preparation["sample_id"])
                    self.assertEqual(result["parent_id"], vial)
                    self.assertEqual(result["preparation_id"], measured["preparation"]["id"])
                    self.assertEqual(result["factor"], factor)
                    self.assertEqual(result["status"], "ok")
                    self.assertAlmostEqual(result["concentration_mg_l"], result["diluted_mg_l"] * factor)
                    evidence = request(prefix + "/evidence")
                    self.assertEqual(evidence["direct"]["id"], direct["id"])
                    self.assertEqual(evidence["direct"]["origin_task_id"], original["id"])
                    self.assertEqual(evidence["initial"]["input"]["sample_id"], vial)
                    self.assertEqual([r["sample_id"] for r in evidence["initial"]["raw"]], [vial] * 3)
                    followup = evidence["followup"]
                    self.assertEqual(followup["origin_task_id"], prepared["id"])
                    self.assertEqual(followup["measurement"]["input"]["sample_id"], preparation["sample_id"])
                    self.assertEqual([r["sample_id"] for r in followup["measurement"]["raw"]],
                                     [preparation["sample_id"]] * 3)
                    self.assertEqual(followup["measurement"]["calibration_id"], direct["result"]["calibration_id"])
                    self.assertEqual(followup["approval"], approval)
                    for key, value in preparation.items():
                        self.assertEqual(followup["preparation"][key], value)
                    self.assertEqual(request(approval_path, {"factor": factor})["id"], child["id"])
            for child_id, approval in approvals.items():
                self.assertEqual(self.lab.task(child_id)["approval"], approval)
            self.assertEqual(len(self.lab.history()), 5)
            worker.assert_not_called()
        for task_id, content in before.items():
            self.assertEqual((self.lab.path(task_id) / "task.json").read_bytes(), content)

    def test_fresh_then_reused_direct_requests_share_the_collection_contract(self):
        historical = self.bundle["direct"]
        files = self.bundle["sources"][historical["id"]]["files"]
        response = {"source": files["analysis.py"], "recipe": json.loads(files["recipe.json"]),
                    "views": json.loads(files["views.json"])}
        with patch.object(self.lab, "collect", side_effect=self.collect_requested_sample) as collect, \
                patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "fixture"})) as worker:
            new = self.wait_for_task(self.lab.submit("First B12 request", sample_id="Lot-1")["id"])
            self.assertEqual(new["status"], "verified", new.get("error"))
            self.assertEqual(new["mode"], "fresh generation")
            self.assertEqual(new["result"]["sample_id"], "Lot-1")
            again = self.wait_for_task(self.lab.submit("Second B12 request", sample_id="Lot-2")["id"])
            self.assert_reused(again, new)
            self.assertEqual(again["result"]["sample_id"], "Lot-2")
            self.assertEqual([call.args for call in collect.call_args_list], [(new["id"],), (again["id"],)])
            worker.assert_called_once()

    def test_fresh_prepared_release_from_reused_parent_retains_bound_provenance(self):
        original = self.seed_live("direct")
        known = self.bundle["followup"]
        files = self.bundle["sources"][known["id"]]["files"]
        response = {"source": files["analysis.py"], "recipe": json.loads(files["recipe.json"]),
                    "views": json.loads(files["views.json"])}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "fixture"})) as worker:
            direct = self.wait_for_task(self.lab.submit("B12")["id"])
            self.assert_reused(direct, original)
            generated = self.wait_for_task(self.lab.approve(direct["id"], factor=2)["id"])
            self.assertEqual(generated["status"], "verified", generated.get("error"))
            self.assertEqual(generated["parent_verification"]["source_revision"], direct["revision"])
            self.assertEqual(generated["verification"]["source_revision"], generated["revision"])
            reused = self.wait_for_task(self.lab.approve(direct["id"], factor=4)["id"])
            self.assert_reused(reused, generated)
            self.assertEqual(reused["origin_parent_verification"], generated["parent_verification"])
            self.assertEqual(reused["parent_verification"], generated["parent_verification"])
            worker.assert_called_once()

    def test_unbound_historical_run_is_preserved_and_new_request_builds_verified_source(self):
        old = self.seed_live("direct")
        folder = self.lab.path(old["id"])
        save(folder / "task.json", {key: value for key, value in old.items() if key != "verification"})
        before = (folder / "task.json").read_bytes()
        files = self.bundle["sources"][old["id"]]["files"]
        response = {"source": files["analysis.py"], "recipe": json.loads(files["recipe.json"]),
                    "views": json.loads(files["views.json"])}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "fixture"})) as worker:
            new = self.wait_for_task(self.lab.submit("B12")["id"])
            self.assertEqual(new["status"], "verified", new.get("error"))
            self.assertIn("lacks revision-bound verification", new["reuse_rejections"][old["id"]][0])
            self.assertEqual(new["mode"], "fresh generation")
            self.assertNotEqual(new["id"], old["id"])
            worker.assert_called_once()
        self.assertEqual(before, (folder / "task.json").read_bytes())

    def test_release_from_superseded_verification_profile_is_not_reused(self):
        # The public archive was verified under optical-checks@1, whose single
        # calibration could not tell some wrong formulas from the right one.
        old = self.seed_live("direct")
        folder = self.lab.path(old["id"])
        save(folder / "task.json", self.bundle["direct"])
        self.assertEqual(self.bundle["direct"]["context"]["verification_profile"], "optical-checks@1")
        files = self.bundle["sources"][old["id"]]["files"]
        response = {"source": files["analysis.py"], "recipe": json.loads(files["recipe.json"]),
                    "views": json.loads(files["views.json"])}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "fixture"})) as worker:
            new = self.wait_for_task(self.lab.submit("B12")["id"])
            self.assertEqual(new["status"], "verified", new.get("error"))
            self.assertEqual(new["reuse_rejections"][old["id"]], ["Incompatible verification_profile"])
            self.assertEqual(new["mode"], "fresh generation")
            self.assertEqual(new["context"]["verification_profile"], "optical-checks@2")
            worker.assert_called_once()

    def test_prepared_reuse_preserves_distinct_experimental_and_original_parent_receipts(self):
        old = self.bundle["direct"]
        files = self.bundle["sources"][old["id"]]["files"]
        response = {"source": files["analysis.py"] + "\n# independently generated direct release",
                    "recipe": json.loads(files["recipe.json"]), "views": json.loads(files["views.json"])}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "new direct worker"})):
            current = self.wait_for_task(self.lab.submit("B12")["id"])
        self.assertEqual(current["status"], "verified", current.get("error"))
        original = self.seed_live("direct")
        prepared = self.seed_live("followup")
        with patch("factory.assays.b12.b12_build.invoke_worker") as worker:
            child = self.wait_for_task(self.lab.approve(current["id"], factor=4)["id"])
            self.assert_reused(child, prepared)
            worker.assert_not_called()
        self.assertNotEqual(child["parent_revision"], child["origin_parent_revision"])
        self.assertEqual(child["origin_parent_task_id"], original["id"])
        self.assertEqual(child["origin_parent_worker"], original["worker"])
        self.assertEqual(child["origin_parent_verification"], prepared["parent_verification"])
        self.assertEqual(child["parent_verification"], verification_receipt(
            current["revision"], child["parent_checks"], current["worker"], child["release_contract"]))

    def test_above_range_result_missing_concentration_fails_without_offering_approval(self):
        # This candidate satisfies the public cases but omits the required null for the live vial.
        source = """import json, sys
sample = json.load(sys.stdin)
cal = sample["calibration"]
values = sample["absorbances"]
in_range = all(cal["low"] <= value <= cal["high"] for value in values)
result = {"sample_id": sample["sample_id"], "calibration_id": cal["id"],
          "status": "ok" if in_range else "review"}
if in_range:
    result["concentration_mg_l"] = (sum(values) / len(values) - cal["intercept"]) / cal["slope"]
elif sample["sample_id"] != "U-01":
    result["concentration_mg_l"] = None
print(json.dumps(result))
"""
        files = self.bundle["sources"][self.bundle["direct"]["id"]]["files"]
        response = {"source": source, "recipe": json.loads(files["recipe.json"]),
                    "views": json.loads(files["views.json"])}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(response, {"method": "fixture"})):
            task = self.wait_for_task(self.lab.submit("Measure B12 at 550 nm")["id"])
        acquisition = read_json(self.lab.path(task["id"]) / "acquisition.json")
        self.assertTrue(acquisition["finding"]["above_range"])
        self.assertEqual(task["status"], "failed")
        self.assertIn("concentration_mg_l", task["error"])
        self.assertNotIn("result", task)
        self.assertNotIn("proposal", task)
        with self.assertRaisesRegex(ValueError, "verified direct above-range run"):
            self.lab.approve(task["id"])
        self.assertEqual(len(self.lab.history()), 1)

    def test_mismatched_acquisition_or_result_identity_fails_closed(self):
        self.seed_live("direct")
        for corrupt in ("raw", "input", "result"):
            with self.subTest(corrupt=corrupt):
                def collect(task_id):
                    data = self.collect_requested_sample(task_id)
                    if corrupt == "raw":
                        data["raw"][0]["sample_id"] = "wrong"
                    elif corrupt == "input":
                        data["input"]["sample_id"] = "wrong"
                    return data

                def execute(source, payload):
                    data = json.loads(payload)
                    return {"sample_id": "wrong" if corrupt == "result" else data["sample_id"],
                            "calibration_id": data["calibration"]["id"], "status": "review",
                            "concentration_mg_l": None}, "fixture"

                with patch.object(self.lab, "collect", side_effect=collect), \
                        patch("factory.assays.b12.lab.execute", side_effect=execute), \
                        patch("factory.assays.b12.b12_build.invoke_worker", side_effect=AssertionError("unexpected generation")) as worker:
                    direct = self.lab.submit("B12", sample_id="Requested")
                    record = self.wait_for_task(direct["id"])
                    self.assertEqual(record["status"], "failed")
                    self.assertFalse(record.get("result"))
                    self.assertIn("sample", record["error"].lower())
                    worker.assert_not_called()

    def test_failed_prepared_reuse_can_retry_as_fresh_generation(self):
        direct = self.seed_live("direct")
        prepared = self.seed_live("followup")
        select = self.lab.select_source

        def interrupted(task, folder):
            self.assertEqual(select(task, folder)["origin_task_id"], prepared["id"])
            raise RuntimeError("interrupted after release selection")

        with patch.object(self.lab, "select_source", side_effect=interrupted):
            child_id = self.lab.approve(direct["id"], 4)["id"]
            failed = self.wait_for_task(child_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["mode"], "verified source reuse")
        # The original is no longer eligible when the user retries the approved task.
        self.lab.update(prepared["id"], status="failed")
        files = self.bundle["sources"][prepared["id"]]["files"]
        candidate = {"source": files["analysis.py"] + "\n# replacement revision",
                     "recipe": json.loads(files["recipe.json"]), "views": json.loads(files["views.json"])}
        receipt = {"method": "fixture", "cli": "fixture", "model": "replacement"}
        with patch("factory.assays.b12.b12_build.invoke_worker", return_value=(candidate, receipt)) as worker:
            self.lab.retry(child_id)
            recovered = self.wait_for_task(child_id)
        worker.assert_called_once()
        self.assertEqual(recovered["status"], "verified", recovered.get("error"))
        self.assertEqual(recovered["mode"], "fresh generation")
        self.assertFalse(any(key.startswith("origin_") for key in recovered))
        self.assertNotEqual(recovered["revision"], prepared["revision"])
        self.assertEqual(recovered["worker"], receipt)
        self.assertEqual(recovered["parent_id"], direct["id"])
        self.assertEqual(recovered["approval"], failed["approval"])
        self.assertEqual(recovered["verification"], verification_receipt(
            recovered["revision"], recovered["checks"], receipt, recovered["release_contract"]))

    def test_missing_prepared_capability_requests_worker_and_preserves_direct_source(self):
        source = self.seed_live("direct")
        folder = self.lab.path(source["id"])
        original = {name: (folder / name).read_bytes() for name in (*b12_build.FILES, "task.json")}
        with patch("factory.assays.b12.b12_build.invoke_worker", side_effect=RuntimeError("injected worker failure")) as worker:
            approved = self.lab.approve(source["id"], factor=4)
            failed = self.wait_for_task(approved["id"])
        worker.assert_called_once()
        self.assertEqual(failed["status"], "failed")
        self.assertIn("injected worker failure", failed["error"])
        self.assertFalse(all(case["pass"] for case in failed["parent_checks"]))
        self.assertEqual(failed["parent_revision"], source["revision"])
        for name, content in original.items():
            self.assertEqual((folder / name).read_bytes(), content)

    def test_approval_and_volume_validation(self):
        direct = self.seed_live("direct")
        with patch.object(self.lab.pool, "submit"):
            for factor in (0, 3, True, "4", None):
                with self.subTest(factor=factor), self.assertRaises(ValueError):
                    self.lab.approve(direct["id"], factor=factor)
            child = self.lab.approve(direct["id"], factor=4)
            valid = dict(sample_id="new", parent_id="U-01", sample_ml=0.5, final_ml=2.0, unit="mL")
            for change in ({"parent_id": "someone else"}, {"sample_id": "U-01"},
                           {"final_ml": 1}, {"unit": "L"}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    self.lab.prepare(child["id"], {**valid, **change})
            self.assertFalse(self.lab.task(child["id"]).get("preparation"))
            for sample_id in ("", " wrong ", None, "A" * 121):
                with self.subTest(sample_id=sample_id), self.assertRaises(ValueError):
                    self.lab.submit("B12", sample_id=sample_id)

    def test_only_compatible_direct_evidence_can_authorize_prepared_source(self):
        direct = self.seed_live("direct")
        self.seed_live("followup")
        folder = self.lab.path(direct["id"])
        with patch.object(self.lab.pool, "submit") as dispatch:
            save(folder / "task.json", {**direct, "context": {**direct["context"], "project": "foreign"}})
            with self.assertRaisesRegex(ValueError, "project"):
                self.lab.approve(direct["id"], factor=4)
            save(folder / "task.json", direct)
            for key, value in (("units", "mV"), ("settings", {"wavelength_nm": 600})):
                data = read_json(folder / "acquisition.json")
                data["raw"][0][key] = value
                save(folder / "acquisition.json", data)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.lab.approve(direct["id"], factor=4)
                save(folder / "acquisition.json", self.bundle["initial"])
            dispatch.assert_not_called()

    def test_tampered_direct_source_rejects_request_with_inspectable_reason(self):
        original = self.seed_live("direct")
        (self.lab.path(original["id"]) / "analysis.py").write_text("# changed")
        with patch("factory.assays.b12.b12_build.invoke_worker") as worker:
            record = self.wait_for_task(self.lab.submit("B12", sample_id="Lot-X")["id"])
        self.assertEqual(record["status"], "failed")
        self.assertIn("digest mismatch", record["reuse_rejections"][original["id"]][0])
        worker.assert_not_called()

    def test_unavailable_parent_verification_does_not_dispatch_revision(self):
        direct = self.seed_live("direct")
        report = self.bundle["followup"]["parent_checks"]
        for case in report:
            if case["name"] in ("prepared-2x", "prepared-4x"):
                case["actual"] = {"error": "execution unavailable"}
        with patch("factory.assays.b12.lab.verify_candidate", return_value=report), patch("factory.assays.b12.b12_build.invoke_worker") as worker:
            failed = self.wait_for_task(self.lab.approve(direct["id"], factor=4)["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["parent_checks"], report)
        worker.assert_not_called()

    def test_rerun_dispatch_forwards_only_explicit_retry(self):
        with self.presenter() as request, patch.object(self.lab, "rerun", return_value={}) as rerun:
            path = "/api/tasks/example/rerun"
            request(path, {})
            rerun.assert_called_once_with("example")
            request(path, {"retry_of": "rejected-attempt"})
            rerun.assert_called_with("example", retry_of="rejected-attempt")

    def test_archive_is_never_selected_as_live_source(self):
        archive_only = Lab(self.store / "readonly", archive=self.bundle, allow_generation=False)
        self.addCleanup(archive_only.close)
        live = Lab(self.store / "empty", archive=self.bundle)
        self.addCleanup(live.close)
        with patch("factory.assays.b12.b12_build.invoke_worker", side_effect=RuntimeError("no live release")) as worker:
            with self.assertRaisesRegex(ValueError, "Archive-only"):
                archive_only.submit("B12", sample_id="other")
            with self.assertRaisesRegex(ValueError, "read-only"):
                live.approve(self.bundle["direct"]["id"], factor=4)
            worker.assert_not_called()
            request = live.submit("B12", sample_id="other")
            live.pool.shutdown()
            task = live.task(request["id"])
            worker.assert_called_once()
            self.assertEqual(task["status"], "failed")
            self.assertIn("no live release", task["error"])
            self.assertFalse(task.get("origin_task_id"))
