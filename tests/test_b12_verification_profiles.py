"""Archives keep validating under the verification profile they were produced with."""
from copy import deepcopy
import unittest

from factory.assays.b12.archive import validate_archive
from factory.assays.b12.archive_verification import SUITES, suite_for
from factory.assays.b12.optics import PROFILE
from factory.context import ROOT, read_json
from tests.b12_release_fixtures import current_checks


class VerificationProfileTests(unittest.TestCase):
    def setUp(self):
        self.bundle = read_json(ROOT / "public/b12/completed.json")

    def current_archive(self):
        """The public archive's bytes, re-verified and recorded under the current profile."""
        bundle = deepcopy(self.bundle)
        direct, child = bundle["direct"], bundle["followup"]
        direct_source = bundle["sources"][direct["id"]]["files"]["analysis.py"]
        child_source = bundle["sources"][child["id"]]["files"]["analysis.py"]
        for task in (direct, child):
            task["context"] = dict(PROFILE)
        direct["checks"] = current_checks(direct_source, False)
        child["parent_checks"] = current_checks(direct_source, True)
        child["checks"] = current_checks(child_source, True)
        return bundle

    def test_public_archive_is_a_legacy_optical_checks_v1_record(self):
        self.assertEqual(self.bundle["direct"]["context"]["verification_profile"], "optical-checks@1")
        self.assertIs(suite_for(self.bundle["direct"]["context"]), SUITES["optical-checks@1"])
        validate_archive(deepcopy(self.bundle))

    def test_current_profile_archive_validates_against_the_new_suite(self):
        bundle = self.current_archive()
        self.assertIs(suite_for(bundle["direct"]["context"]), SUITES["optical-checks@2"])
        validate_archive(bundle)

    def test_records_must_match_their_own_profile(self):
        # @1 evidence relabelled as @2 lacks the new calibration cases.
        relabelled = deepcopy(self.bundle)
        for role in ("direct", "followup"):
            relabelled[role]["context"] = dict(PROFILE)
        with self.assertRaisesRegex(ValueError, "missing required checks"):
            validate_archive(relabelled)
        mixed = self.current_archive()
        mixed["followup"]["context"] = self.bundle["followup"]["context"]
        with self.assertRaisesRegex(ValueError, "context"):
            validate_archive(mixed)
        unknown = deepcopy(self.bundle)
        unknown["direct"]["context"] = {**PROFILE, "verification_profile": "optical-checks@0"}
        with self.assertRaisesRegex(ValueError, "pinned B12 profile"):
            validate_archive(unknown)

    def test_current_evidence_with_a_wrong_answer_is_rejected(self):
        bundle = self.current_archive()
        case = next(c for c in bundle["direct"]["checks"] if c["name"] == "direct-steep-calibration")
        case["actual"]["concentration_mg_l"] = -19.75
        with self.assertRaisesRegex(ValueError, "direct-steep-calibration"):
            validate_archive(bundle)


if __name__ == "__main__":
    unittest.main()
