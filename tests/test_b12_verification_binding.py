from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from factory import b12_build
from factory.b12_reuse import release_contract, select_release
from factory.b12_verification import UNBOUND_VERIFICATION, validate_receipt, verification_receipt
from factory.context import ROOT, read_json


class VerificationBindingTests(unittest.TestCase):
    def setUp(self):
        bundle = read_json(ROOT / "public/b12/completed.json")
        self.task = bundle["direct"]
        self.files = {name: source.encode("utf-8")
                      for name, source in bundle["sources"][self.task["id"]]["files"].items()}
        self.contract = release_contract(False)
        self.task["verification"] = verification_receipt(
            self.task["revision"], self.task["checks"], self.task["worker"], self.contract)

    def test_valid_binding_is_stable_across_serialized_key_order(self):
        contract = dict(reversed(self.contract.items()))
        self.assertEqual(validate_receipt(self.task, self.files, contract), self.task["verification"])

    def test_changed_source_with_recomputed_task_revision_still_fails(self):
        files = {**self.files, "analysis.py": b"print('{}')"}
        task = {**self.task, "revision": b12_build.content_revision(files)}
        with self.assertRaisesRegex(ValueError, "verification evidence mismatch"):
            validate_receipt(task, files, self.contract)
        # Copying the new revision field onto the old receipt also leaves its
        # evidence digest tied to the source that was actually tested.
        task["verification"] = {**task["verification"], "source_revision": task["revision"]}
        with self.assertRaisesRegex(ValueError, "verification evidence mismatch"):
            validate_receipt(task, files, self.contract)

    def test_selector_refuses_rehashed_source_with_original_worker_and_checks(self):
        with tempfile.TemporaryDirectory() as store:
            folder = Path(store) / self.task["id"]
            folder.mkdir()
            for name, content in self.files.items():
                (folder / name).write_bytes(content)
            record = folder / "task.json"
            record.write_text(json.dumps(self.task))
            selected, rejected = select_release(store, prepared=False)
            self.assertEqual(selected["id"], self.task["id"])
            self.assertFalse(rejected)

            (folder / "analysis.py").write_text("print('{}')")
            record.write_text(json.dumps({**self.task, "revision": b12_build.revision(folder)}))
            selected, rejected = select_release(store, prepared=False)
            self.assertIsNone(selected)
            self.assertIn("verification evidence mismatch", rejected[self.task["id"]][0])

    def test_receipt_detects_stale_checks_worker_and_contract(self):
        for field in ("checks", "worker", "contract"):
            with self.subTest(field=field):
                task = deepcopy(self.task)
                contract = deepcopy(self.contract)
                if field == "checks":
                    task["checks"][0]["actual"]["concentration_mg_l"] = 0
                elif field == "worker":
                    task["worker"]["model"] = "another-model"
                else:
                    contract["verification_profile"] = "optical-checks@2"
                with self.assertRaisesRegex(ValueError, "verification evidence mismatch"):
                    validate_receipt(task, self.files, contract)

    def test_unbound_history_is_inspectable_and_requires_fresh_release(self):
        del self.task["verification"]
        original = deepcopy(self.task)
        with self.assertRaises(ValueError) as rejection:
            validate_receipt(self.task, self.files, self.contract)
        self.assertEqual(str(rejection.exception), UNBOUND_VERIFICATION)
        self.assertEqual(self.task, original)
        for invalid in (None, {}, "changed"):
            with self.subTest(receipt=invalid), self.assertRaisesRegex(ValueError, "verification evidence mismatch"):
                validate_receipt({**self.task, "verification": invalid}, self.files, self.contract)
