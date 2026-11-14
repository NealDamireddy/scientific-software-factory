"""A candidate that omits a measurement guard must fail scientific verification."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from factory.release_repository import ReleaseRepository
from factory.scientific_release import verify_release
from tests.test_scientific_release import handoff, resign


# Source intervals delimit complete guards in the standalone fixture candidate.
# Mutants retain the optics, calibration math, error handling and other guards.
MUTATIONS = (
    ("raw counts", "        if any(type(count)", "        if min(blank, sample)",
     {"negative detector counts", "fractional detector counts", "saturated detector counts"}),
    ("elapsed time", '        if finite(reading["elapsed_s"]', '        replicate = reading["replicate"]',
     {"nonfinite elapsed time", "negative elapsed time"}),
    ("UTC timestamp", '        timestamp = reading["timestamp"]', '        if finite(reading["elapsed_s"]',
     {"missing measurement timestamp", "malformed measurement timestamp", "non-UTC measurement timestamp"}),
    ("replicate identity", '        replicate = reading["replicate"]', "        dark, blank, sample =",
     {"repeated replicate identity", "nonpositive replicate identity", "fractional replicate identity"}),
)


class MutationTests(unittest.TestCase):
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
