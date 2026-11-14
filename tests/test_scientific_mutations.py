"""A candidate that omits a measurement guard must fail scientific verification."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from factory.release_repository import ReleaseRepository
from factory.scientific_analysis import analyze_release
from factory.scientific_contract import cases
from factory.scientific_release import verify_release
from tests.test_scientific_release import handoff, resign


# Source intervals delimit complete guards in the standalone fixture candidate.
# Mutants retain the optics, calibration math, error handling and other guards.
MUTATIONS = (
    ("raw counts", "        if any(type(count)", "        if min(blank, sample)",
     {"negative detector counts", "fractional detector counts", "saturated detector counts"}),
    ("dark-corrected signals", "        if min(blank, sample) <= dark:", "        values.append(",
     {"negative dark-corrected signals", "negative dark-corrected signals in one replicate"}),
    ("elapsed time", '        if finite(reading["elapsed_s"]', '        replicate = reading["replicate"]',
     {"nonfinite elapsed time", "negative elapsed time", "positive infinite elapsed time", "negative infinite elapsed time"}),
    ("detector count units", '        if reading["unit"] != "counts"', '        if reading["simulated"]',
     {"measurement units"}),
    ("measurement settings", "        if any(type(reading[key])", '        if type(reading["schema_version"])',
     {"wavelength compatibility", "path length compatibility"}),
    ("UTC timestamp", '        timestamp = reading["timestamp"]', '        if finite(reading["elapsed_s"]',
     {"missing measurement timestamp", "malformed measurement timestamp", "non-UTC measurement timestamp"}),
    ("replicate identity", '        replicate = reading["replicate"]', "        dark, blank, sample =",
     {"repeated replicate identity", "nonpositive replicate identity", "fractional replicate identity"}),
)


class MutationTests(unittest.TestCase):
    def test_verified_analysis_withholds_negative_dark_corrected_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ReleaseRepository(Path(directory) / "releases.sqlite")
            for kind in ("concentration", "time_course"):
                baseline = handoff(kind)
                release_id = verify_release(repository, **baseline)["release_id"]
                self.assertIsNotNone(release_id)
                _, _, clean, _ = next(cases(kind, baseline["compiled_recipe"]))
                reference = analyze_release(repository, release_id, clean)
                self.assertTrue(all(row["concentration_mg_l"] is not None for row in reference["results"]))
                for indices in ((0, 1, 2), (2,)):
                    with self.subTest(kind=kind, invalid_replicates=indices):
                        payload = deepcopy(clean)
                        records = payload["groups"][0]["records"]
                        for index in indices:
                            # Raw counts remain valid integers. Both corrected signals are
                            # negative, yet their ratio matches the original transmission.
                            records[index].update(dark_counts=40000, blank_counts=7232,
                                                  sample_counts=(35904, 37952, 38976)[index])
                        result = analyze_release(repository, release_id, payload)
                        self.assertEqual(result["calibration_id"], reference["calibration_id"])
                        self.assertEqual(result["results"][1:], reference["results"][1:])
                        affected = result["results"][0]
                        self.assertEqual(affected["sample_id"], reference["results"][0]["sample_id"])
                        if kind == "time_course":
                            self.assertEqual(affected["timestamp"], records[0]["timestamp"])
                        self.assertIsNone(affected["concentration_mg_l"])
                        self.assertIsNone(affected["replicate_sd_mg_l"])
                        self.assertIsInstance(affected["review_reason"], str)
                        self.assertTrue(affected["review_reason"].strip())

    def test_sandboxed_mutants_preserve_verified_release(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ReleaseRepository(Path(directory) / "releases.sqlite")
            for kind in ("concentration", "time_course"):
                baseline = handoff(kind)
                good = verify_release(repository, **baseline)
                original = good["release_id"]
                self.assertIsNotNone(original, [c for c in good["checks"] if not c["passed"]])
                before = repository.load(original)
                for guard, first, after, expected_failures in MUTATIONS:
                    with self.subTest(kind=kind, removed_guard=guard):
                        mutant = deepcopy(baseline)
                        source = mutant["files"]["analysis.py"].decode()
                        start = source.index(first)
                        stop = source.index(after, start)
                        mutant["files"]["analysis.py"] = (source[:start] + source[stop:]).encode()
                        resign(mutant)
                        result = verify_release(repository, **mutant)
                        failures = {check["name"] for check in result["checks"] if check["status"] == "failed"}
                        self.assertIsNone(result["release_id"])
                        self.assertTrue(expected_failures <= failures, failures)
                        self.assertEqual(repository.active("demo-lab", "visible-assay", kind), original)
                        self.assertEqual(repository.load(original), before)

    def test_candidate_accepting_positive_infinity_cannot_replace_release(self):
        guard = b'if finite(reading["elapsed_s"], "elapsed time") < 0:'
        partial_guard = b'if math.isnan(reading["elapsed_s"]) or reading["elapsed_s"] < 0:'
        with tempfile.TemporaryDirectory() as directory:
            repository = ReleaseRepository(Path(directory) / "releases.sqlite")
            for kind in ("concentration", "time_course"):
                with self.subTest(kind=kind):
                    data = handoff(kind)
                    original = verify_release(repository, **data)["release_id"]
                    self.assertIsNotNone(original)
                    source = data["files"]["analysis.py"]
                    self.assertEqual(source.count(guard), 1)
                    data["files"]["analysis.py"] = source.replace(guard, partial_guard)
                    resign(data)
                    result = verify_release(repository, **data)
                    self.assertIsNone(result["release_id"])
                    failures = [check["name"] for check in result["checks"] if not check["passed"]]
                    self.assertEqual(failures, ["positive infinite elapsed time"])
                    self.assertEqual(repository.active("demo-lab", "visible-assay", kind), original)
