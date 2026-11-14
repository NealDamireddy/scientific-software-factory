"""A correctly re-signed candidate must pass the frozen-fit checks to displace a release."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from factory.release_repository import ReleaseRepository
from factory.scientific_release import verify_release
from tests.test_scientific_release import handoff, resign


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise AssertionError(f"Expected one candidate mutation site: {old}")
    return source.replace(old, new)


def omit_finite_fit_checks(source, exception=None):
    # The fixture validates the four individual inputs and checks the complete fit again.
    # Preserve positive slope, ordered range and the separate finite result guards.
    source = replace_once(source, "finite(calibration[key], key)", "calibration[key]")
    gate = "not all(map(math.isfinite, (slope, intercept, low, high)))"
    if exception is None:
        return replace_once(source, gate + " or ", "")
    return replace_once(source, gate, f"({gate} and not ({exception}))")


def refit_from_standards(source):
    # Reuse the candidate's actual concentration regression and preserve timepoint identity.
    start = '    calibration = data["calibration"]\n    if calibration["unit"]'
    return replace_once(source, start, '''    if data["experiment_type"] == "time_course" and data["standards"]:
        return calibration_parameters({**data, "experiment_type": "concentration"})
''' + start)


class FrozenCalibrationPublicationTests(unittest.TestCase):
    def test_resigned_mutants_preserve_verified_time_course(self):
        data = handoff("time_course")
        with tempfile.TemporaryDirectory() as folder:
            repository = ReleaseRepository(Path(folder) / "releases.sqlite")
            baseline = verify_release(repository, **data)
            original = baseline["release_id"]
            self.assertIsNotNone(original, [c for c in baseline["checks"] if not c["passed"]])
            active_key = ("demo-lab", "visible-assay", "time_course")
            self.assertEqual(repository.active(*active_key), original)
            manifest, files = repository.load(original)
            self.assertEqual(files, data["files"])
            plan = [(c["name"], c["category"]) for c in manifest["checks"]]
            source = files["analysis.py"].decode()
            positive_slope = "positive infinite frozen slope"
            lower_bound = "negative infinite frozen low"
            upper_bound = "positive infinite frozen high"
            cases = (
                ("omitted finite fit guards", omit_finite_fit_checks(source),
                 {positive_slope, lower_bound, upper_bound, "NaN frozen low", "NaN frozen high"}),
                ("infinite slope", omit_finite_fit_checks(source, "slope == math.inf"), {positive_slope}),
                ("infinite lower bound", omit_finite_fit_checks(source, "low == -math.inf"), {lower_bound}),
                ("infinite upper bound", omit_finite_fit_checks(source, "high == math.inf"), {upper_bound}),
                ("refit supplied standards", refit_from_standards(source),
                 {"supplied standards cannot replace frozen fit"}),
            )
            for label, changed, expected_failures in cases:
                with self.subTest(mutant=label):
                    proposal = deepcopy(data)
                    proposal["files"]["analysis.py"] = changed.encode()
                    resign(proposal)
                    self.assertNotEqual(proposal["candidate"]["source_revision"], manifest["source_revision"])
                    report = verify_release(repository, **proposal)
                    self.assertIsNone(report["release_id"])
                    self.assertEqual([(c["name"], c["category"]) for c in report["checks"]], plan)
                    statuses = {c["name"]: c["status"] for c in report["checks"]}
                    self.assertEqual(statuses, {
                        name: "failed" if name in expected_failures else "passed" for name, _ in plan
                    })
                    self.assertTrue(expected_failures <= statuses.keys())
                    reopened = ReleaseRepository(repository.path)
                    self.assertEqual(reopened.active(*active_key), original)
                    # load checks the raw stored manifest against original and every artifact's bytes.
                    self.assertEqual(reopened.load(original), (manifest, files))
