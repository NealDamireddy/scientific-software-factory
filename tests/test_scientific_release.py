from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from factory.b12_build import content_revision
from factory.context import ROOT, digest
from factory.release_repository import ReleaseRepository, canonical
from factory.scientific_analysis import analyze_release, public_input
from factory.scientific_contract import cases, compare
from factory.scientific_release import metrics, verify_release


def handoff(kind):
    # WO-6 owns the canonical fixture. Use its frozen public projection on pre-integration branches.
    profile_file = ROOT / "registry/virtual-uvvis.profile.json"
    profile = json.loads(profile_file.read_bytes()) if profile_file.exists() else {
        "schema_version": 1, "profile_id": "virtual-uvvis@1", "wavelengths_nm": [450, 550, 650],
        "path_lengths_mm": [10], "replicate_limits": {"min": 1, "max": 10},
        "operations": ["measure-absorbance"], "blank_reference_required": True, "simulated": True}
    pins = dict(instrument_id="uvvis-demo-01", profile_id=profile["profile_id"],
                profile_sha256=digest(canonical(profile)))
    recipe = dict(schema_version=1, **pins, settings=dict(operation="measure-absorbance", replicates=3,
                                                          wavelength_nm=650, path_length_mm=10),
                  sample_ids=["vial-q17"])
    lab = dict(kind="lab", lab_id="demo-lab", revision=2, revision_id="lab-v2", sha256=digest(b"lab fixture"))
    project = dict(kind="project", lab_id=lab["lab_id"], project_id="visible-assay", revision=5,
                   revision_id="project-v5", sha256=digest(b"project fixture"),
                   lab_revision=2, lab_sha256=lab["sha256"])
    context = dict(experiment_type=kind, lab=lab, project=project, instrument=dict(**pins, lab_id=lab["lab_id"]),
                   specification_sha256=digest(b"approved specification"), compiled_recipe_sha256=digest(canonical(recipe)))
    files = {"analysis.py": (Path(__file__).parent / "fixtures/scientific_analysis.py").read_bytes(),
             "recipe.json": canonical(recipe), "views.json": canonical(dict(title="Assay", metrics=metrics(kind)))}
    candidate = dict(experiment_type=kind, verification_contract=kind + "@1",
                     context_sha256=digest(canonical(context)), worker_receipt=dict(method="fixture", outcome="completed"))
    handoff = dict(experiment_type=kind, profile=profile, context=context, compiled_recipe=recipe,
                   candidate=candidate, files=files)
    resign(handoff)
    return handoff


def resign(handoff):
    files, candidate = handoff["files"], handoff["candidate"]
    candidate["artifacts"] = {k: digest(v) for k, v in files.items()}
    candidate["source_revision"] = content_revision(files)
    candidate["worker_receipt"]["source_revision"] = candidate["source_revision"]


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repository = ReleaseRepository(self.folder / "releases.sqlite")

    def verify(self, handoff):
        return verify_release(self.repository, **handoff)

    def promote(self, handoff):
        result = self.verify(handoff)
        self.assertIsNotNone(result["release_id"], [c for c in result["checks"] if not c["passed"]])
        return result["release_id"]

    def test_publish_and_reopen_both_contracts(self):
        for kind in ("concentration", "time_course"):
            with self.subTest(kind=kind):
                data = handoff(kind)
                release = self.promote(data)
                repo = ReleaseRepository(self.repository.path)
                self.assertEqual(repo.active("demo-lab", "visible-assay", kind), release)
                self.assertIsNone(repo.active("demo-lab", "foreign-project", kind))
                manifest, artifacts = repo.load(release)
                self.assertEqual(artifacts, data["files"])
                self.assertEqual(manifest["context"], data["context"])
                self.assertEqual(manifest["artifacts"], data["candidate"]["artifacts"])
                self.assertEqual((manifest["rel_tol"], manifest["abs_tol"]), (1e-7, 1e-7))
                self.assertEqual(manifest["worker_receipt"]["source_revision"], manifest["source_revision"])
                probes = list(cases(kind, data["compiled_recipe"]))
                for _, _, payload, expected in (probes[1], probes[2], probes[3]):
                    compare(analyze_release(repo, release, payload), expected)
                incompatible = deepcopy(probes[0][2])
                incompatible["calibration"]["wavelength_nm"] = 450
                for row in analyze_release(repo, release, incompatible)["results"]:
                    self.assertIsNone(row["concentration_mg_l"])
                    self.assertTrue(row["review_reason"])

    def test_public_projection_excludes_private_fields(self):
        data = handoff("time_course")
        payload = next(cases("time_course", data["compiled_recipe"]))[2]
        expected = deepcopy(payload)
        for obj in (payload, payload["calibration"], payload["groups"][0], payload["groups"][0]["records"][0]):
            obj["private_truth"] = "simulator-only marker"
        self.assertEqual(public_input(payload, "time_course"), expected)

    def test_new_release_keeps_old_revision_retrievable(self):
        data = handoff("time_course")
        original = self.promote(data)
        self.assertEqual(self.promote(data), original)
        data["files"]["analysis.py"] += b"\n# independently verified revision two\n"
        resign(data)
        revised = self.promote(data)
        self.assertNotEqual(original, revised)
        self.assertEqual(self.repository.active("demo-lab", "visible-assay", "time_course"), revised)
        self.assertEqual(self.repository.load(original)[1], handoff("time_course")["files"])

    def test_failed_checks_preserve_previous_manifest_and_files(self):
        data = handoff("concentration")
        previous = self.promote(data)
        data["files"]["analysis.py"] = b"print('{}')"
        data["files"]["recipe.json"] = canonical({**data["compiled_recipe"], "sample_ids": ["other"]})
        data["files"]["views.json"] = b'{"title":"Only a title","metrics":[]}'
        resign(data)
        data["candidate"]["context_sha256"] = "0" * 64
        report = self.verify(data)
        self.assertIsNone(report["release_id"])
        failures = {c["name"] for c in report["checks"] if not c["passed"]}
        self.assertTrue({"compiled recipe equality", "candidate worker and context", "display contract",
                         "nonzero intercept, sample SD and identities"} <= failures)
        self.assertEqual(self.repository.active("demo-lab", "visible-assay", "concentration"), previous)
        self.assertEqual(self.repository.load(previous)[1], handoff("concentration")["files"])

    def test_bad_metadata_and_malformed_artifacts_fail_closed(self):
        for mutation, failure in [
            (lambda d: d["context"]["project"].update(lab_revision=3), "pinned context and acquisition settings"),
            (lambda d: d["context"].update(experiment_type="concentration"), "pinned context and acquisition settings"),
            (lambda d: d["profile"].update(profile_id="other"), "pinned context and acquisition settings"),
            (lambda d: d["candidate"].update(source_revision="bad"), "candidate artifact and source digests"),
            (lambda d: d["files"].update({"analysis.py": b"syntax !"}), "candidate artifact and source digests"),
            (lambda d: d["files"].update({"recipe.json": b'{"a":1,"a":2}'}), "compiled recipe equality"),
            (lambda d: d["files"].update({"views.json": b" " * 65537}), "display contract"),
            (lambda d: d.update(experiment_type="kinetics"), "supported verification contract"),
        ]:
            data = handoff("time_course")
            mutation(data)
            if data["candidate"]["source_revision"] != "bad":
                resign(data)
            with self.subTest(failure=failure):
                report = self.verify(data)
                self.assertIsNone(report["release_id"])
                self.assertIn(failure, [c["name"] for c in report["checks"] if not c["passed"]])

    def test_sandboxed_candidate_cannot_change_trusted_files(self):
        data = handoff("time_course")
        sentinel = self.folder / "frozen-calibration.json"
        sentinel.write_bytes(b"calibration must survive")
        original = digest(sentinel.read_bytes())
        data["files"]["analysis.py"] = f"open({str(sentinel)!r}, 'w').write('changed')\n".encode() + data["files"]["analysis.py"]
        resign(data)
        result = self.verify(data)
        self.assertIsNone(result["release_id"])
        self.assertEqual(digest(sentinel.read_bytes()), original)
        self.assertTrue(any(not c["passed"] and c["category"] == "numerical" for c in result["checks"]))

    def test_atomic_rollback_and_corrupt_artifact_rejection(self):
        data = handoff("concentration")
        release = self.promote(data)
        with sqlite3.connect(self.repository.path) as db:
            db.execute("""CREATE TRIGGER fail_switch BEFORE UPDATE ON scientific_active
                          BEGIN SELECT RAISE(ABORT, 'injected switch failure'); END""")
        data["files"]["analysis.py"] += b"\n# Different verified revision\n"
        resign(data)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected switch failure"):
            self.verify(data)
        self.assertEqual(self.repository.active("demo-lab", "visible-assay", "concentration"), release)
        with sqlite3.connect(self.repository.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM scientific_manifests").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM scientific_blobs").fetchone()[0], 3)
            db.execute("UPDATE scientific_blobs SET content=x'00'")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.repository.load(release)
