"""Admission at the B12 presenter's historical-run boundary."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from factory import demo
from factory.context import ROOT, read_json
from factory.lab import Handler, Lab, ThreadingHTTPServer


HISTORICAL_RUN = ROOT / "public/b12/completed.json"


def assert_archive_rejected(test, package, diagnostic):
    """Also used with a WO-16 rejected-attempt export on the integrated tree."""
    with tempfile.TemporaryDirectory() as temp:
        store = Path(temp) / "live"
        # Lab initializes the service for GET /api/tasks and /api/tasks/<id>.
        # Rejection here must occur before a completed task can be returned.
        with test.assertRaisesRegex(ValueError, diagnostic):
            lab = Lab(store, archive=package, allow_generation=False)
            lab.close()
        test.assertFalse(store.exists())

        path = Path(temp) / "previous.json"
        path.write_text(json.dumps(package))
        with patch.object(demo, "check_sandbox", side_effect=RuntimeError("replay unavailable")), \
                patch.object(demo, "check_port", return_value="available"), \
                patch("factory.replay_bundle.replay_package") as replay:
            checks, archive = demo.readiness(0, path, archive_only=True)
        test.assertIsNone(archive)
        failures = [detail for status, name, detail in checks
                    if status == "FAIL" and name == "Previous run"]
        test.assertEqual(len(failures), 1, checks)
        test.assertRegex(failures[0], diagnostic)
        replay.assert_not_called()


def add_completed_attempt(package, role):
    """WO-16 journal shape on committed readings; the combined tree exercises its actual writer."""
    task = package[role]
    if role == "direct":
        measurement = package["initial"]
        measurement["finding"] = deepcopy(task["finding"])
        identifier = "3" * 32
    else:
        measurement = task["measurement"]
        identifier = "4" * 32
    raw = measurement["raw"]
    attempt = {
        "id": identifier, "status": "completed", "sample_id": measurement["input"]["sample_id"],
        "revision": task["revision"], "calibration_id": task["result"]["calibration_id"],
        "preparation": deepcopy(task.get("preparation")), "finding": deepcopy(measurement["finding"]),
        "settings": json.loads(package["sources"][task["id"]]["files"]["recipe.json"]),
        "started_at": raw[0]["timestamp"], "acquired_at": raw[-1]["timestamp"],
        "finished_at": measurement.get("time", raw[-1]["timestamp"]), "raw": deepcopy(raw),
    }
    measurement["attempt_id"] = identifier
    task.update(acquisition_attempts=[attempt], acquisition_status="completed")
    return attempt


def fourfold(package):
    child = package["followup"]
    child["approval"]["factor"] = 4
    for prep in (child["preparation"], child["measurement"]["input"]["preparation"]):
        prep["final_ml"] = prep["sample_ml"] * 4
    for result in (child["result"], child["measurement"]["result"]):
        result["factor"] = 4
        result["concentration_mg_l"] = result["diluted_mg_l"] * 4
    child.pop("score", None)


def reused_package(historical):
    """Construct two new task receipts using the archived prepared source, as WO-19 exports them."""
    package = deepcopy(historical)
    direct, child = package["direct"], package["followup"]
    v2 = historical["followup"]
    source = historical["sources"][v2["id"]]
    contract = {
        **direct["context"], "capabilities": ["direct", "prepared"],
        "units": {"detector": "counts", "concentration": "mg/L", "volume": "mL"},
        "settings": {**json.loads(source["files"]["recipe.json"]), "path_length_mm": 10},
        "input_schema": "b12-assay-input@1", "output_schema": "b12-assay-result@1",
        "approved_libraries": ["json", "math", "statistics", "sys"], "calibration_contract": "b12-optical@1",
    }
    for task, run_id in ((direct, "1" * 32), (child, "2" * 32)):
        task.update(id=run_id, mode="verified source reuse", origin_task_id=v2["id"],
                    origin_parent_revision=v2["parent_revision"], origin_parent_checks=deepcopy(v2["parent_checks"]),
                    revision=v2["revision"], checks=deepcopy(v2["checks"]), views=deepcopy(v2["views"]),
                    worker=deepcopy(v2["worker"]), release_contract=deepcopy(contract))
    package["sources"] = {t["id"]: {"files": deepcopy(source["files"]), "diff": ""} for t in (direct, child)}
    direct["result"].update(parent_id=None, preparation_id=None, factor=None, diluted_mg_l=None)
    direct["sample_id"] = direct["result"]["sample_id"]
    proposal = direct["proposal"]
    proposal.update(factors=[2, 4], calibration_id=package["initial"]["calibration"]["id"],
                    volumes="One volume sample plus one (2×) or three (4×) volumes of matching solvent",
                    reason="The readings exceed the strongest standard. The protocol permits a 2× or 4× dilution.")
    approval = child["approval"]
    approval.update(origin=direct["id"], parent_sample_id=direct["sample_id"],
                    evidence={k: deepcopy(proposal[k]) for k in ("readings", "upper_standard", "calibration_id")})
    child.update(parent_id=direct["id"], parent_revision=direct["revision"], parent_checks=deepcopy(direct["checks"]))
    prep_id = "prep-" + child["id"]
    for prep in (child["preparation"], child["measurement"]["input"]["preparation"]):
        prep["id"] = prep_id
    for result in (child["result"], child["measurement"]["result"]):
        result["preparation_id"] = prep_id
    for check in package["checks"]:
        if check["name"] == "Preparation documented":
            check["reference"] = prep_id
    fourfold(package)
    return package


class ArchiveConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.bundle = read_json(HISTORICAL_RUN)
        self.child = self.bundle["followup"]
        self.measurement = self.child["measurement"]

    def reject(self, diagnostic):
        assert_archive_rejected(self, self.bundle, "(?i)" + diagnostic)

    def test_task_result_changed_to_999(self):
        self.child["result"]["concentration_mg_l"] = 999
        self.reject("concentration_mg_l|result")

    def test_unrelated_original_vial_even_when_preparation_and_result_copies_agree(self):
        for record in (self.child["preparation"], self.measurement["input"]["preparation"],
                       self.child["result"], self.measurement["result"]):
            record["parent_id"] = "unrelated-vial"
        self.reject("parent")

    def test_changed_approved_factor(self):
        self.child["approval"]["factor"] = 4
        self.reject("factor|approved dilution")

    def test_missing_approval(self):
        del self.child["approval"]
        self.reject("approval")

    def test_empty_v2_verification_checks(self):
        self.child["checks"] = []
        self.reject("check")

    def test_matching_task_and_measurement_result_must_agree_with_counts_and_volumes(self):
        for result in (self.child["result"], self.measurement["result"]):
            result["diluted_mg_l"] = 499.5
            result["concentration_mg_l"] = 999
        self.reject("concentration_mg_l|diluted_mg_l|result")

    def test_origin_protocol_and_source_revision(self):
        for record, field, value, diagnostic in (
                ("approval", "origin", self.child["id"], "origin|approval"),
                ("approval", "protocol", "b12-optical@2", "protocol"),
                ("measurement", "revision", self.bundle["direct"]["revision"], "revision")):
            with self.subTest(record=record, field=field):
                package = deepcopy(self.bundle)
                package["followup"][record][field] = value
                assert_archive_rejected(self, package, "(?i)" + diagnostic)

    def test_one_source_cannot_both_decline_and_pass_the_prepared_contract(self):
        direct = self.bundle["direct"]
        self.bundle["sources"][self.child["id"]] = deepcopy(self.bundle["sources"][direct["id"]])
        self.child["views"] = deepcopy(direct["views"])
        self.child["revision"] = self.measurement["revision"] = direct["revision"]
        self.reject("source|revision")

    def test_prepared_vial_units_actual_volumes_and_id(self):
        for field, value, diagnostic in (("unit", "L", "unit"),
                                         ("sample_ml", True, "sample_ml|volume"),
                                         ("final_ml", 4, "factor|volume"),
                                         ("id", "another-preparation", "preparation")):
            with self.subTest(field=field):
                package = deepcopy(self.bundle)
                child = package["followup"]
                child["preparation"][field] = value
                child["measurement"]["input"]["preparation"][field] = value
                assert_archive_rejected(self, package, "(?i)" + diagnostic)

    def test_measurement_input_must_use_original_calibration(self):
        self.measurement["input"]["calibration"]["slope"] *= 2
        self.reject("calibration|slope")

    def test_range_finding_must_agree_with_raw_counts(self):
        self.measurement["finding"]["in_range"] = False
        self.reject("finding|in_range")

    def test_missing_measurement_and_evidence_records(self):
        for path in (("followup", "measurement"), ("followup", "parent_checks"),
                     ("direct", "checks"), ("initial", "raw"), ("environment", "dependency_lock"),
                     ("scientific_review",), ("checks",)):
            with self.subTest(path=path):
                package = deepcopy(self.bundle)
                record = package
                for field in path[:-1]:
                    record = record[field]
                del record[path[-1]]
                assert_archive_rejected(self, package, "(?i)" + path[-1])

    def test_failed_v2_mandatory_check_cannot_use_v1_exemption(self):
        name = "prepared-2x"
        parent = next(c for c in self.child["parent_checks"] if c["name"] == name)
        self.assertFalse(parent["pass"])
        index = next(i for i, c in enumerate(self.child["checks"]) if c["name"] == name)
        self.child["checks"][index] = deepcopy(parent)
        self.reject("check|prepared-2x")

    def test_passing_flag_requires_real_observation_and_trusted_expectation(self):
        for forge_expected in (False, True):
            with self.subTest(forge_expected=forge_expected):
                package = deepcopy(self.bundle)
                check = next(c for c in package["followup"]["checks"] if c["name"] == "prepared-4x")
                check["actual"]["concentration_mg_l"] = 999
                if forge_expected:
                    check["expected"]["concentration_mg_l"] = 999
                assert_archive_rejected(self, package, "(?i)check|prepared-4x")

    def test_duplicate_case_cannot_replace_a_required_check(self):
        self.child["checks"][-1] = deepcopy(self.child["checks"][0])
        self.reject("check|duplicate")

    def test_valid_counts_from_rejected_analysis_cannot_be_published_as_completed(self):
        add_completed_attempt(self.bundle, "direct")
        attempt = add_completed_attempt(self.bundle, "followup")
        # Keep valid public counts and the retained "ok" measurement. The
        # rejected candidate never acquired authority to publish that estimate.
        attempt.update(status="rejected", failure={"field": "analysis", "reason": "candidate sample ID mismatch"})
        self.child["acquisition_status"] = "rejected"
        self.reject("attempt.*status|acquisition_status")

    def test_attempt_id_and_raw_are_required_on_direct_and_followup(self):
        for role in ("direct", "followup"):
            for mutation in ("missing ID", "different ID", "missing raw", "different raw"):
                with self.subTest(role=role, mutation=mutation):
                    package = deepcopy(self.bundle)
                    attempt = add_completed_attempt(package, role)
                    measurement = package["initial"] if role == "direct" else package["followup"]["measurement"]
                    if mutation == "missing ID":
                        del measurement["attempt_id"]
                    elif mutation == "different ID":
                        measurement["attempt_id"] = "f" * 32
                    elif mutation == "missing raw":
                        del attempt["raw"]
                    else:
                        attempt["raw"][0]["dark_counts"] += 1
                    diagnostic = "attempt_id" if "ID" in mutation else "raw"
                    assert_archive_rejected(self, package, diagnostic)

    def test_completed_retry_links_its_new_readings_and_retains_earlier_rejected_counts(self):
        direct = add_completed_attempt(self.bundle, "direct")
        current = add_completed_attempt(self.bundle, "followup")
        previous = deepcopy(current)
        previous.update(id="5" * 32, status="rejected", failure={"field": "raw", "reason": "Saturated detector"})
        del previous["finding"]
        previous["raw"][0]["sample_counts"] = 65535
        current["retry_of"] = previous["id"]
        self.child["acquisition_attempts"].insert(0, previous)
        with tempfile.TemporaryDirectory() as temp:
            lab = Lab(Path(temp) / "live", archive=self.bundle, allow_generation=False)
            self.addCleanup(lab.close)
            retained = lab.evidence(self.child["id"])
            self.assertEqual(retained["initial"]["attempt_id"], direct["id"])
            child = retained["followup"]
            self.assertEqual(child["acquisition_attempts"], [previous, current])
            self.assertEqual(child["measurement"]["attempt_id"], current["id"])
            self.assertEqual(child["measurement"]["raw"], current["raw"])
            self.assertNotEqual(previous["raw"], child["measurement"]["raw"])

    def test_replay_disagreement_on_working_sandbox_blocks_archive_only_startup(self):
        with patch.object(demo, "check_sandbox", return_value="working isolation"), \
                patch.object(demo, "check_port", return_value="available"), \
                patch("factory.replay_bundle.replay_package",
                      side_effect=ValueError("rerun differs from the saved result")) as replay:
            checks, archive = demo.readiness(0, HISTORICAL_RUN, archive_only=True)
        self.assertIn(("FAIL", "Archive replay", "rerun differs from the saved result"), checks)
        self.assertIsNone(archive)
        replay.assert_called_once()

    def test_coordinated_fourfold_change_disagrees_with_twofold_historical_proposal(self):
        fourfold(self.bundle)
        self.reject("factor|proposal")

    def test_reused_prepared_source_binds_matching_revision_to_original_generation(self):
        package = reused_package(self.bundle)
        with tempfile.TemporaryDirectory() as temp:
            lab = Lab(Path(temp) / "live", archive=package, allow_generation=False)
            self.addCleanup(lab.close)
            self.assertEqual({t["id"] for t in lab.history()}, {package["direct"]["id"], package["followup"]["id"]})
            for t in lab.history():
                self.assertEqual(t["origin_task_id"], self.child["id"])
                self.assertEqual(t["revision"], self.child["revision"])
                self.assertEqual(t["worker"], self.child["worker"])
            saved = lab.evidence(package["followup"]["id"])
            self.assertEqual(saved, package)
            self.assertEqual(saved["followup"]["result"]["factor"], 4)

    def test_reused_records_cannot_disagree_about_the_same_origin(self):
        for field, diagnostic in (("origin_task_id", "origin|provenance"),
                                  ("worker", "worker|provenance"), ("parent_checks", "check")):
            with self.subTest(field=field):
                package = reused_package(self.bundle)
                child = package["followup"]
                if field == "origin_task_id":
                    child[field] = child["id"]   # cannot be its own original release
                elif field == "worker":
                    child[field]["model"] = "another-worker"
                else:
                    child[field] = deepcopy(self.child["parent_checks"])
                assert_archive_rejected(self, package, "(?i)" + diagnostic)

    def test_new_approval_pins_original_sample_and_public_evidence(self):
        for field, diagnostic in (("sample_id", "sample"), ("parent_sample_id", "sample"),
                                  ("readings", "readings|evidence"),
                                  ("upper_standard", "upper_standard|evidence"),
                                  ("calibration_id", "calibration|evidence")):
            with self.subTest(field=field):
                package = reused_package(self.bundle)
                approval = package["followup"]["approval"]
                if field == "sample_id":
                    package["direct"][field] = "other-vial"
                elif field == "parent_sample_id":
                    approval[field] = "other-vial"
                else:
                    approval["evidence"][field] = None
                assert_archive_rejected(self, package, "(?i)" + diagnostic)

    def test_revealed_signed_error_must_match_saved_score(self):
        self.child["score"]["signed_error_mg_l"] = 999
        self.reject("signed_error_mg_l")

    def test_boolean_in_only_one_copy_of_sample_volume_is_invalid(self):
        self.measurement["input"]["preparation"]["sample_ml"] = True
        self.reject("sample_ml|preparation")

    def make_followup_outside_range(self):
        # Keep the original calibration and child identity. Use above-range counts
        # in the child records, as a simulator can observe after a real dilution.
        for source, target in zip(self.bundle["initial"]["raw"], self.measurement["raw"]):
            for field in ("dark_counts", "blank_counts", "sample_counts"):
                target[field] = source[field]
        self.measurement["finding"] = deepcopy(self.bundle["direct"]["finding"])
        self.measurement["input"]["absorbances"] = deepcopy(self.measurement["finding"]["absorbances"])
        for result in (self.child["result"], self.measurement["result"]):
            result.update(status="review", concentration_mg_l=None, diluted_mg_l=None, factor=None)
        del self.child["score"]
        del self.child["replay"]
        self.bundle["scientific_review"].append("Follow-up outside calibration.")

    def test_outside_range_cannot_publish_a_diluted_estimate_or_falsify_preparation(self):
        self.make_followup_outside_range()
        for field, bad in (("diluted_mg_l", 999), ("parent_id", "unrelated-vial"),
                           ("preparation_id", "another-preparation"), ("factor", 4)):
            with self.subTest(field=field):
                package = deepcopy(self.bundle)
                child = package["followup"]
                for result in (child["result"], child["measurement"]["result"]):
                    result[field] = bad
                assert_archive_rejected(self, package, field)

    def test_valid_followup_outside_range_retains_review_and_withheld_result(self):
        self.make_followup_outside_range()
        with tempfile.TemporaryDirectory() as temp:
            lab = Lab(Path(temp) / "live", archive=self.bundle, allow_generation=False)
            self.addCleanup(lab.close)
            saved = lab.task(self.child["id"])
            self.assertEqual(saved["result"]["status"], "review")
            self.assertIsNone(saved["result"]["concentration_mg_l"])
            self.assertEqual(saved["measurement"]["raw"], self.measurement["raw"])

    def test_valid_history_is_inspectable_when_replay_is_unavailable(self):
        with patch.object(demo, "check_sandbox", side_effect=RuntimeError("replay unavailable")), \
                patch("factory.replay_bundle.replay_package") as replay:
            checks, archive = demo.readiness(0, HISTORICAL_RUN, archive_only=True)
        self.assertFalse([detail for status, _, detail in checks if status == "FAIL"], checks)
        self.assertIn(("WARN", "Offline sandbox", "replay unavailable"), checks)
        self.assertIn(("WARN", "Archive replay"), [(s, n) for s, n, _ in checks])
        replay.assert_not_called()

        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / "live"
            lab = Lab(store, archive=archive, allow_generation=False)
            self.addCleanup(lab.close)
            with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
                server.lab = lab
                address = f"127.0.0.1:{server.server_port}"
                server.hosts = {address}
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def get(suffix):
                    with urlopen(f"http://{address}/api/tasks{suffix}", timeout=5) as response:
                        return json.load(response)

                try:
                    listing = get("")
                    self.assertIs(listing["allow_generation"], False)
                    ids = {self.bundle[role]["id"] for role in ("direct", "followup")}
                    self.assertEqual({task["id"] for task in listing["tasks"]}, ids)
                    for role in ("direct", "followup"):
                        original = self.bundle[role]
                        task = get("/" + original["id"])
                        self.assertIs(task["archived"], True)
                        self.assertEqual(task["mode"], "previous completed run")
                        self.assertEqual(task["result"], original["result"])
                        self.assertEqual(task["revision"], original["revision"])
                        self.assertEqual(get("/" + original["id"] + "/source"),
                                         self.bundle["sources"][original["id"]])
                    self.assertEqual(get("/" + self.child["id"] + "/evidence"), self.bundle)
                finally:
                    server.shutdown()
                    thread.join()
            self.assertFalse(store.exists())
