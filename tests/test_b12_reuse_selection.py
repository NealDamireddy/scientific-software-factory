"""Release eligibility is decided on verified original B12 source and contract evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from factory import b12_build
from factory.b12_reuse import read_release, release_contract, select_release, validate_parent_checks
from factory.context import ROOT, read_json
from tests.b12_release_fixtures import verified_task


class ReleaseSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name)
        self.bundle = read_json(ROOT / "public/b12/completed.json")

    def seed_original(self, kind):
        task = verified_task(self.bundle, kind)
        folder = self.store / task["id"]
        folder.mkdir(exist_ok=True)
        for name, source in self.bundle["sources"][task["id"]]["files"].items():
            (folder / name).write_text(source)
        self.save_task(task)
        return folder, task

    def save_task(self, task):
        (self.store / task["id"] / "task.json").write_text(json.dumps(task))

    def test_bound_originals_prefer_matching_capability(self):
        _, prepared = self.seed_original("followup")
        selected, reasons = select_release(self.store, False)
        self.assertIsNone(selected)
        self.assertIn("parent release is missing", reasons[prepared["id"]][0])
        _, direct = self.seed_original("direct")
        for need_prepared, original in ((False, direct), (True, prepared)):
            with self.subTest(need_prepared=need_prepared):
                selected, rejected = select_release(self.store, need_prepared)
                self.assertEqual(selected["id"], original["id"])
                self.assertEqual(selected["worker"], original["worker"])
                self.assertEqual(selected["checks"], original["checks"])
                self.assertEqual(b12_build.content_revision(selected["files"]), original["revision"])
                if need_prepared:
                    self.assertEqual(selected["parent_checks"], original["parent_checks"])
                    self.assertEqual(selected["parent_revision"], direct["revision"])
                    self.assertEqual(rejected[direct["id"]], ["Missing capabilities: prepared"])

    def test_parent_revision_resolves_to_verified_live_original(self):
        direct_folder, direct = self.seed_original("direct")
        _, child = self.seed_original("followup")
        for changes, reason in (({"parent_revision": "0" * 64}, "parent revision"),
                                ({"parent_id": "0" * 32}, "parent release is missing"),
                                ({"parent_id": child["id"]}, "direct parent"),
                                ({"parent_id": "../foreign"}, "parent release identity"),
                                ({"approval": {"origin": "0" * 32}}, "preparation approval"),
                                ({"parent_verification": None}, "Parent verification receipt")):
            with self.subTest(changes=changes):
                self.save_task({**child, **changes})
                selected, rejected = select_release(self.store, True)
                self.assertIsNone(selected)
                self.assertIn(reason, rejected[child["id"]][0])

        self.save_task(child)
        (direct_folder / "analysis.py").write_text("print('{}')")
        new_revision = b12_build.revision(direct_folder)
        self.save_task({**direct, "revision": new_revision})
        self.save_task({**child, "parent_revision": new_revision})
        selected, rejected = select_release(self.store, True)
        self.assertIsNone(selected)
        self.assertIn(child["id"], rejected)

    def test_prepared_checks_bound_to_their_actual_parent(self):
        self.seed_original("direct")
        _, child = self.seed_original("followup")
        # A harmless extra output still passes the numerical contract, but changes
        # the recorded parent report independently of its verification receipt.
        child["parent_checks"][0]["actual"]["annotation"] = "stale report"
        self.save_task(child)
        selected, rejected = select_release(self.store, True)
        self.assertIsNone(selected)
        self.assertIn("Parent verification receipt", rejected[child["id"]][0])

    def test_reused_direct_run_resolves_to_original_bytes_and_verification(self):
        direct_folder, direct = self.seed_original("direct")
        child_folder, child = self.seed_original("followup")
        reused = {**direct, "id": "a" * 32, "mode": "verified source reuse",
                  "origin_task_id": direct["id"]}
        folder = self.store / reused["id"]
        folder.mkdir()
        for name in b12_build.FILES:
            (folder / name).write_bytes((direct_folder / name).read_bytes())
        self.save_task(reused)
        self.save_task({**child, "parent_id": reused["id"],
                        "approval": {**child["approval"], "origin": reused["id"]}})
        selected = read_release(child_folder, True)
        self.assertEqual(selected["parent_revision"], direct["revision"])
        self.assertEqual(selected["parent_origin_task_id"], direct["id"])
        self.assertEqual(selected["parent_worker"], direct["worker"])
        for changes in ({"verification": {}}, {"worker": {}}, {"origin_task_id": reused["id"]},
                        {"origin_task_id": child["id"]}, {"origin_task_id": "../outside"}):
            with self.subTest(changes=changes):
                self.save_task({**reused, **changes})
                with self.assertRaises(ValueError):
                    read_release(child_folder, True)

    def test_rejects_changed_artifacts_even_when_status_verified(self):
        folder, task = self.seed_original("direct")
        (folder / "analysis.py").write_text("print('{}')")
        selected, reasons = select_release(self.store, False)
        self.assertIsNone(selected)
        self.assertIn("digest mismatch", reasons[task["id"]][0])

    def test_rejects_incompatible_recipe_even_with_matching_revision(self):
        folder, task = self.seed_original("direct")
        recipe = read_json(folder / "recipe.json")
        (folder / "recipe.json").write_text(json.dumps(dict(recipe, wavelength_nm=600)))
        self.save_task(dict(task, revision=b12_build.revision(folder)))
        selected, reasons = select_release(self.store, False)
        self.assertIsNone(selected)
        self.assertIn("550", reasons[task["id"]][0])

    def test_rejects_incompatible_contracts_and_receipts(self):
        _, direct = self.seed_original("direct")
        contract = release_contract(False)
        changes = (
            ({"context": dict(direct["context"], project="foreign")}, "project"),
            ({"release_contract": dict(contract, settings=dict(contract["settings"], path_length_mm=8))}, "settings"),
            ({"release_contract": dict(contract, units=dict(contract["units"], concentration="mol/L"))}, "units"),
            ({"release_contract": dict(contract, verification_profile="optical-checks@0")}, "verification_profile"),
            ({"release_contract": dict(contract, capabilities=["direct", "prepared"])}, "capabilities"),
            ({"worker": {}}, "worker"),
            ({"worker": {"method": "codex exec"}}, "worker CLI or model"),
            ({"checks": direct["checks"][1:]}, "verification contract"),
            ({"checks": [*direct["checks"], direct["checks"][0]]}, "verification contract"),
            ({"checks": [{**direct["checks"][0], "pass": False}, *direct["checks"][1:]]}, "verification contract"),
        )
        for fields, expected in changes:
            with self.subTest(expected=expected):
                self.save_task(dict(direct, **fields))
                selected, reasons = select_release(self.store, False)
                self.assertIsNone(selected)
                self.assertIn(expected, reasons[direct["id"]][0])

    def test_passing_receipt_cannot_substitute_checks_or_outputs(self):
        folder, direct = self.seed_original("direct")
        for field, edits in (("actual", {"concentration_mg_l": 56}),
                             ("actual", {"concentration_mg_l": float("nan")}),
                             ("expected", {"status": "different-contract"})):
            with self.subTest(field=field, edits=edits):
                altered = deepcopy(direct)
                altered["checks"][0][field].update(edits)
                self.save_task(altered)
                with self.assertRaisesRegex(ValueError, "verification contract"):
                    read_release(folder)

    def test_parent_verifier_must_show_direct_pass_and_missing_preparation(self):
        folder, prepared = self.seed_original("followup")
        for field, value in (("parent_checks", prepared["checks"]),
                             ("parent_checks", []), ("parent_revision", prepared["revision"])):
            with self.subTest(field=field):
                self.save_task(dict(prepared, **{field: value}))
                with self.assertRaisesRegex(ValueError, "verification"):
                    read_release(folder, prepared=True)

    def test_parent_failure_must_be_a_safe_decline_for_both_valid_preparations(self):
        folder, prepared = self.seed_original("followup")
        for case, changes in (
                ("prepared-2x", {"error": "sandbox unavailable"}),
                ("prepared-4x", {"status": "ok", "concentration_mg_l": 99}),
                ("prepared-2x", {"status": "review", "diluted_mg_l": 8}),
                ("prepared-4x", {"calibration_id": "wrong"}),
                ("prepared-2x", {"sample_id": "wrong"}),
                ("prepared-one-outside", {"status": "ok", "concentration_mg_l": 5}),
                ("prepared-invalid-unit", {"error": "sandbox unavailable"})):
            with self.subTest(case=case, changes=changes):
                task = deepcopy(prepared)
                check = next(row for row in task["parent_checks"] if row["name"] == case)
                check["actual"] = changes if "error" in changes else {**check["actual"], **changes}
                check["pass"] = False
                with self.assertRaisesRegex(ValueError, "Parent verification"):
                    validate_parent_checks(task["parent_checks"])
                self.save_task(task)
                with self.assertRaisesRegex(ValueError, "Parent verification"):
                    read_release(folder, prepared=True)

    def test_ignores_read_only_and_reused_runs(self):
        _, direct = self.seed_original("direct")
        for changes in ({"mode": "previous completed run"}, {"archived": True},
                        {"origin_task_id": "a" * 32}, {"mode": "reused release"}):
            with self.subTest(changes=changes):
                self.save_task(dict(direct, **changes))
                self.assertEqual(select_release(self.store, False), (None, {}))

    def test_rejects_task_folder_identity_mismatch_without_following_it(self):
        folder, direct = self.seed_original("direct")
        (folder / "task.json").write_text(json.dumps(dict(direct, id="../foreign")))
        selected, reasons = select_release(self.store, False)
        self.assertIsNone(selected)
        self.assertIn("identity", reasons[direct["id"]][0])
