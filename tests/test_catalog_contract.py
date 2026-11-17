"""Subclass CatalogRepositoryContract and unittest.TestCase; provide open_repository().

Each test gets a fresh logical store. Repeated calls to the zero-argument callable
open independent repository instances against that same store, including on threads.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from threading import Barrier

from factory.catalog_contract import APPROVE, PROPOSE, READ, RECORD_EVIDENCE
from factory.context import digest
from factory.context_repository import RevisionConflict, canonical_json
from tests.fixtures.catalog_examples import LAB, Caller, catalog, evidence, source


class CatalogRepositoryContract:
    def setUp(self):
        super().setUp()
        self.repo = self.open_repository()
        self.curator = Caller()

    def test_reopen_catalog_and_source(self):
        manual = self.repo.save("source", LAB, "manual", source(), expected_revision=0, principal=self.curator)
        draft = self.repo.save("catalog", LAB, "uvvis", catalog(manual.pin.revision_id),
                               expected_revision=0, principal=self.curator)
        reopened = self.open_repository()
        self.assertEqual(reopened.get("source", LAB, "manual", principal=self.curator), manual)
        self.assertEqual(reopened.get("catalog", LAB, "uvvis", principal=self.curator), draft)
        self.assertEqual(draft.state, "draft")

    def new_catalog(self):
        manual = self.repo.save("source", LAB, "manual", source(), expected_revision=0, principal=self.curator)
        draft = self.repo.save("catalog", LAB, "uvvis", catalog(manual.pin.revision_id),
                               expected_revision=0, principal=self.curator)
        return manual, draft

    def test_approved_profile_pin_survives_updates_and_reopen(self):
        manual, first = self.new_catalog()
        reviewer = Caller("reviewer", actions=[APPROVE])
        receipt = self.repo.approve(first.pin, principal=reviewer)
        self.assertEqual((receipt.pin, receipt.approver), (first.pin, "reviewer"))
        self.assertIsNotNone(datetime.fromisoformat(receipt.approved_at).utcoffset())
        self.assertEqual(self.repo.approve(first.pin, principal=reviewer), receipt)
        with self.assertRaises(RevisionConflict):
            self.repo.approve(first.pin, principal=self.curator)

        new_manual = self.repo.save("source", LAB, "manual", {**source(), "document_revision": "3"},
                                    expected_revision=1, principal=self.curator)
        proposal = Caller("worker-2", is_human=False, actions=[PROPOSE])
        revised = self.repo.save("catalog", LAB, "uvvis", catalog(new_manual.pin.revision_id),
                                 expected_revision=1, principal=proposal)
        self.assertEqual((revised.state, revised.author, revised.predecessor_id),
                         ("draft", "worker-2", first.pin.revision_id))
        self.assertNotEqual(revised.pin.revision_id, first.pin.revision_id)
        self.assertNotEqual(revised.pin.sha256, first.pin.sha256)
        self.assertIsNotNone(datetime.fromisoformat(revised.created_at).utcoffset())
        with self.assertRaises(RevisionConflict):
            self.repo.approve(first.pin, principal=reviewer)
        new_receipt = self.repo.approve(revised.pin, principal=reviewer)

        reopened = self.open_repository()
        original = reopened.get(first.pin.kind, first.pin.lab_id, first.pin.record_id,
                                revision=first.pin.revision, principal=self.curator)
        current = reopened.get("catalog", LAB, "uvvis", principal=self.curator)
        self.assertEqual(original, replace(first, approval=receipt))
        self.assertEqual(original.state, "approved")
        self.assertEqual(current, replace(revised, approval=new_receipt))
        self.assertEqual(reopened.history("catalog", LAB, "uvvis", principal=self.curator), (original, current))
        self.assertEqual(reopened.history("source", LAB, "manual", principal=self.curator), (manual, new_manual))
        self.assertEqual(new_manual.predecessor_id, manual.pin.revision_id)
        cited_id = original.payload["claims"][0]["citations"][0]["source_revision_id"]
        self.assertEqual(reopened.get_by_id("source", LAB, cited_id, principal=self.curator), manual)
        self.assertEqual(reopened.get_by_id("catalog", LAB, first.pin.revision_id, principal=self.curator), original)

    def test_evidence_origin_and_correction_history(self):
        before = evidence()
        recorder = Caller("test-curator", actions=[RECORD_EVIDENCE])
        original = self.repo.save("evidence", LAB, "test-8", before, expected_revision=0, principal=recorder)
        self.assertEqual(original.author, "test-curator")
        self.assertEqual(original.pin.sha256, digest(canonical_json(before).encode()))
        self.assertIsNone(original.state)
        corrected = {**before, "origin": "physical", "result": "fail", "limitations": ["alignment error"]}
        new = self.repo.save("evidence", LAB, "test-8", corrected, expected_revision=1, principal=self.curator)
        reopened = self.open_repository()
        self.assertEqual(reopened.history("evidence", LAB, "test-8", principal=self.curator), (original, new))
        self.assertEqual(new.predecessor_id, original.pin.revision_id)
        self.assertEqual(original.payload, before)
        self.assertEqual(new.payload, corrected)
        self.assertEqual(date.fromisoformat(original.payload["test_date"]).isoformat(), before["test_date"])

    def test_input_and_result_are_detached(self):
        manual, draft = self.new_catalog()
        original_input = catalog(manual.pin.revision_id)
        new = self.repo.save("catalog", LAB, "uvvis", original_input, expected_revision=1, principal=self.curator)
        self.assertEqual(draft.pin.sha256, new.pin.sha256)
        original_input["claims"].clear()
        new.payload["unresolved_gaps"].append("local mutation")
        stored = self.repo.get("catalog", LAB, "uvvis", principal=self.curator)
        self.assertEqual(stored.payload, draft.payload)
        self.assertEqual(stored.pin.sha256, digest(canonical_json(stored.payload).encode()))

    def test_denied_before_lookup_or_validation_on_every_operation(self):
        _, draft = self.new_catalog()
        for actor in (Caller("other", lab_id="foreign"), Caller("revoked", actions=[])):
            for record_id in ("uvvis", "missing"):
                pin = replace(draft.pin, record_id=record_id)
                calls = [
                    lambda: self.repo.get("catalog", LAB, record_id, revision=-1, principal=actor),
                    lambda: self.repo.history("catalog", LAB, record_id, principal=actor),
                    lambda: self.repo.get_by_id("catalog", LAB, pin.revision_id, principal=actor),
                    lambda: self.repo.approve(pin, principal=actor),
                    lambda: self.repo.save("catalog", LAB, record_id, {}, expected_revision=-1, principal=actor),
                    lambda: self.repo.save("source", LAB, record_id, {}, expected_revision=-1, principal=actor),
                    lambda: self.repo.save("evidence", LAB, record_id, {}, expected_revision=-1, principal=actor),
                ]
                for call in calls:
                    with self.subTest(actor=actor.actor_id, record_id=record_id), self.assertRaises(PermissionError):
                        call()
        self.assertEqual(self.repo.history("catalog", LAB, "uvvis", principal=self.curator), (draft,))

    def test_actor_and_action_boundaries(self):
        _, draft = self.new_catalog()
        agent = Caller("worker", is_human=False)
        with self.assertRaises(PermissionError):
            self.repo.approve(draft.pin, principal=agent)
        curator = Caller(actions=[PROPOSE])
        with self.assertRaises(PermissionError):
            self.repo.approve(draft.pin, principal=curator)
        with self.assertRaises(PermissionError):
            self.repo.save("evidence", LAB, "test", evidence(), expected_revision=0, principal=curator)
        with self.assertRaises(PermissionError):
            self.repo.save("source", LAB, "manual", source(), expected_revision=1,
                           principal=Caller(actions=[RECORD_EVIDENCE]))
        reader = Caller(actions=[READ])
        self.assertEqual(self.repo.get("catalog", LAB, "uvvis", principal=reader), draft)
        reader.actions.clear()
        with self.assertRaises(PermissionError):
            self.repo.get("catalog", LAB, "uvvis", principal=reader)
        for injected in ("lab_id", "project_id", "author", "actor_id", "is_human", "approval", "state"):
            with self.subTest(injected=injected), self.assertRaises(ValueError):
                self.repo.save("catalog", LAB, "uvvis", {**draft.payload, injected: "forged"},
                               expected_revision=1, principal=self.curator)

    def test_only_exact_same_lab_sources_can_be_cited(self):
        manual, draft = self.new_catalog()
        foreign = Caller(lab_id="foreign")
        foreign_manual = self.repo.save("source", "foreign", "manual", source(), expected_revision=0, principal=foreign)
        self.assertNotEqual(manual.pin.revision_id, foreign_manual.pin.revision_id)
        self.assertEqual(self.repo.get("source", "foreign", "manual", principal=foreign), foreign_manual)
        with self.assertRaises(KeyError):
            self.repo.get_by_id("source", LAB, foreign_manual.pin.revision_id, principal=self.curator)
        with self.assertRaises(KeyError):
            self.repo.get_by_id("source", LAB, draft.pin.revision_id, principal=self.curator)
        for source_id in (foreign_manual.pin.revision_id, draft.pin.revision_id, "missing"):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                self.repo.save("catalog", LAB, "uvvis", catalog(source_id), expected_revision=1, principal=self.curator)
        self.assertEqual(self.repo.history("catalog", LAB, "uvvis", principal=self.curator), (draft,))

    def test_structural_validation_and_draft_gaps(self):
        for optional in ("document_revision", "access_date"):
            payload = source()
            del payload[optional]
            self.repo.save("source", LAB, optional, payload, expected_revision=0, principal=self.curator)
        for bad_source in ({"title": "manual", "reference": "doc"}, {**source(), "access_date": "2026-02-30"}):
            with self.assertRaises(ValueError):
                self.repo.save("source", LAB, "bad", bad_source, expected_revision=0, principal=self.curator)
        good = evidence()
        invalid = [{k: v for k, v in good.items() if k != field} for field in good]
        invalid.extend([{**good, "origin": "claimed"}, {**good, "test_date": "not a date"},
                        {**good, "artifact_refs": []}, {**good, "tested_configuration": float("nan")}])
        for bad in invalid:
            with self.subTest(payload=bad), self.assertRaises(ValueError):
                self.repo.save("evidence", LAB, "test", bad, expected_revision=0, principal=self.curator)
        with self.assertRaises(KeyError):
            self.repo.history("evidence", LAB, "test", principal=self.curator)
        payload = {"model": "unsourced", "claims": [{"operation": "unknown"}], "unresolved_gaps": ["missing source"]}
        draft = self.repo.save("catalog", LAB, "draft", payload, expected_revision=0, principal=self.curator)
        self.assertEqual((draft.state, draft.payload), ("draft", payload))

    def test_pin_and_revision_mismatches(self):
        manual, draft = self.new_catalog()
        for key, value in (("revision", 2), ("revision_id", manual.pin.revision_id), ("sha256", "a" * 64)):
            with self.subTest(key=key), self.assertRaises(RevisionConflict):
                self.repo.approve(replace(draft.pin, **{key: value}), principal=self.curator)
        with self.assertRaises(KeyError):
            self.repo.get("catalog", LAB, "uvvis", revision=2, principal=self.curator)
        with self.assertRaises(ValueError):
            self.repo.approve(manual.pin, principal=self.curator)
        for value in (True, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repo.save("catalog", LAB, "uvvis", draft.payload, expected_revision=value, principal=self.curator)
        self.assertEqual(self.repo.get("catalog", LAB, "uvvis", principal=self.curator), draft)

    def race(self, operation):
        barrier = Barrier(2)

        def run(index):
            repo = self.open_repository()
            barrier.wait(timeout=10)
            try:
                return operation(repo, index)
            except RevisionConflict as conflict:
                return conflict

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    def test_concurrent_empty_and_existing_heads(self):
        for kind, initial in (("catalog", {"model": "one", "claims": [], "unresolved_gaps": []}),
                              ("source", source()), ("evidence", evidence())):
            previous = None
            for expected in (0, 1):
                def save(repo, index):
                    return repo.save(kind, LAB, "race", initial, expected_revision=expected,
                                     principal=Caller(f"writer-{index}"))

                results = self.race(save)
                self.assertEqual(sum(isinstance(item, RevisionConflict) for item in results), 1)
                winner = next(item for item in results if not isinstance(item, RevisionConflict))
                self.assertEqual(winner.pin.revision, expected + 1)
                self.assertEqual(winner.predecessor_id, previous.pin.revision_id if previous else None)
                self.assertEqual(self.repo.get(kind, LAB, "race", principal=self.curator), winner)
                previous = winner

    def test_concurrent_approvers_keep_one_receipt(self):
        _, draft = self.new_catalog()

        def approve(repo, index):
            return repo.approve(draft.pin, principal=Caller(f"approver-{index}", actions=[APPROVE]))

        results = self.race(approve)
        self.assertEqual(sum(isinstance(item, RevisionConflict) for item in results), 1)
        winner = next(item for item in results if not isinstance(item, RevisionConflict))
        self.assertEqual(self.open_repository().get("catalog", LAB, "uvvis", principal=self.curator).approval, winner)
