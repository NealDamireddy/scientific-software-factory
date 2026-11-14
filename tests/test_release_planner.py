"""Approval-to-worker contract and source-selection tests with a separate verifier fixture."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from factory.b12_build import content_revision
from factory.context import digest
from factory.release_planner import INPUT_SCHEMA, OUTPUT_SCHEMA, ReleasePlanner
from factory.uvvis_contract import canonical, load_profile, profile_sha256


class Approvals:
    def __init__(self):
        self.records = {}

    def add(self, spec):
        pin = digest(canonical(spec).encode())
        self.records[pin] = deepcopy(spec)
        return pin

    def approved(self, pin):
        return deepcopy(self.records[pin]), {"specification_sha256": pin, "actor": "local-pi"}

    def compile_recipe(self, pin):
        spec, _ = self.approved(pin)
        return dict(schema_version=1, settings=spec["settings"],
                    **{k: spec["instrument"][k] for k in ("instrument_id", "profile_id", "profile_sha256")})


class VerifiedRepository:
    def __init__(self):
        self.current = {}
        self.records = {}

    def active(self, lab, project, kind):
        return self.current.get((lab, project, kind))

    def load(self, release):
        return deepcopy(self.records[release])


def verify(repository, *, experiment_type, context, profile, compiled_recipe, candidate, files):
    # Mirror the WO-9 handoff, including exact byte digests and parent-independent promotion.
    assert profile_sha256(profile) == context["instrument"]["profile_sha256"]
    assert digest(canonical(compiled_recipe).encode()) == context["compiled_recipe_sha256"]
    assert digest(canonical(context).encode()) == candidate["context_sha256"]
    assert candidate["source_revision"] == content_revision(files) == candidate["worker_receipt"]["source_revision"]
    assert candidate["artifacts"] == {k: digest(v) for k, v in files.items()}
    assert candidate["worker_receipt"]["outcome"] == "completed"
    assert experiment_type == context["experiment_type"] == candidate["experiment_type"]
    if json.loads(files["recipe.json"]) != compiled_recipe:
        return {"release_id": None, "checks": [{"passed": False, "detail": "wrong recipe"}]}
    manifest = dict(context=context, source_revision=candidate["source_revision"], experiment_type=experiment_type,
                    verification_contract=candidate["verification_contract"], input_schema=INPUT_SCHEMA,
                    output_schema=OUTPUT_SCHEMA)
    release = digest(canonical(manifest).encode())
    repository.records[release] = manifest, files
    repository.current[context["lab"]["lab_id"], context["project"]["project_id"], experiment_type] = release
    return {"release_id": release, "checks": [{"passed": True}]}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "tasks.sqlite"
        self.approvals = Approvals()
        self.releases = VerifiedRepository()
        self.calls = []
        self.spec = {
            "lab": {"lab_id": "lab", "kind": "lab", "revision": 1, "revision_id": "lab-one", "sha256": "a" * 64},
            "project": {"lab_id": "lab", "project_id": "p", "kind": "project", "revision": 2,
                        "revision_id": "p-two", "sha256": "b" * 64, "lab_revision": 1, "lab_sha256": "a" * 64},
            "instrument": {"lab_id": "lab", "instrument_id": "uvvis-demo-01", "profile_id": "virtual-uvvis@1",
                           "profile_sha256": profile_sha256(load_profile())},
            "settings": {"operation": "measure-absorbance", "wavelength_nm": 650, "path_length_mm": 10, "replicates": 3},
            "experiment_type": "concentration", "verification_contract": "concentration@1",
            "approved_libraries": ["Python statistics"], "validation_criteria": ["positive slope"],
            "operating_restrictions": ["simulated visible channels only"], "units": {"concentration": "mg/L"},
            "analysis_method": "linear fit", "sample_ids": ["vial-q17"], "standards": [],
            "calibration": None, "schedule": None,
            "outputs": ["calibration_id", "sample_id", "concentration_mg_l", "replicate_sd_mg_l", "review_reason"],
        }
        self.pin = self.approvals.add(self.spec)
        self.planner = self.open()

    def open(self, worker=None, verifier=verify):
        return ReleasePlanner(self.approvals, self.releases, self.path, worker=worker or self.worker, verifier=verifier)

    def worker(self, prompt, schema):
        data = json.loads(prompt.split('within this contract.\n')[1].split('\nRevise this')[0])
        self.calls.append(data)
        return ({"source": "print('fixture candidate')\n", "recipe": data["compiled_recipe"],
                 "views": {"title": "Scientific result", "metrics": data["view_metrics"]}},
                {"method": "fixture worker", "model": "fixture"})

    def build(self):
        planned = self.planner.plan(self.pin)
        self.assertEqual((planned["mode"], planned["state"]), ("generate", "pending"))
        ready = self.planner.run(planned["id"])
        self.assertEqual(ready["state"], "candidate_ready")
        return self.planner.verify(planned["id"])

    def test_filtered_generation_retention_and_verified_sample_only_reuse(self):
        first = self.build()
        self.assertEqual(first["state"], "released")
        self.assertNotIn("vial-q17", first["prompt"])
        self.assertNotIn("B12", first["prompt"])
        self.assertIn(self.pin, first["prompt"])
        self.assertEqual(self.calls[0]["project"], self.spec["project"])
        self.assertEqual(first["worker_receipt"]["method"], "fixture worker")
        self.assertEqual(self.open().get(first["id"]), first)
        newer = dict(self.spec, sample_ids=["vial-next"],
                     project=dict(self.spec["project"], revision=3, revision_id="p-three", sha256="d" * 64))
        next_pin = self.approvals.add(newer)
        reuse = self.planner.plan(next_pin)
        self.assertEqual((reuse["state"], reuse["mode"]), ("reused", "reuse"))
        self.assertEqual((reuse["release_id"], reuse["source_revision"]), (first["release_id"], first["source_revision"]))
        self.assertEqual(reuse["context"]["project"], newer["project"])
        self.assertEqual(self.planner.run(reuse["id"]), reuse)
        self.assertEqual(len(self.calls), 1)

    def test_time_course_revision_and_incompatible_settings_leave_old_release(self):
        base = self.build()
        time_course = dict(self.spec, experiment_type="time_course", verification_contract="time_course@1",
                           outputs=[*self.spec["outputs"], "timestamp"], calibration={"id": "c", "sha256": "1"*64,
                               "contract": "absorbance-linear@1", "unit": "mg/L", "settings": self.spec["settings"]})
        pin = self.approvals.add(time_course)
        task = self.planner.plan(pin)
        self.assertEqual((task["mode"], task["parent_release_id"]), ("revise", base["release_id"]))
        self.assertIn("Missing capabilities: timestamp", task["rejections"][base["release_id"]])
        self.assertIn("Incompatible verification_contract", task["rejections"][base["release_id"]])
        self.assertEqual(self.planner.run(task["id"])["state"], "candidate_ready")
        self.assertIn("Revise this verified parent", self.planner.get(task["id"])["prompt"])
        time_release = self.planner.verify(task["id"])
        self.assertEqual(time_release["state"], "released")
        self.assertEqual(self.releases.active("lab", "p", "concentration"), base["release_id"])
        new_cal = dict(time_course["calibration"], sha256="2"*64)
        same = self.planner.plan(self.approvals.add(dict(time_course, calibration=new_cal)))
        self.assertEqual(same["state"], "reused")
        self.assertEqual(same["context"]["calibration_sha256"], "2"*64)
        changed = dict(new_cal, contract="different-calibration@1")
        rejected = self.planner.plan(self.approvals.add(dict(time_course, calibration=changed)))
        self.assertIn("Incompatible calibration_contract", rejected["rejections"][time_release["release_id"]])
        other = dict(self.spec, settings=dict(self.spec["settings"], wavelength_nm=450))
        rejected = self.planner.plan(self.approvals.add(other))
        self.assertIn("Incompatible settings", rejected["rejections"][base["release_id"]])
        self.planner.run(rejected["id"])
        self.planner.verify(rejected["id"])
        old_recipe = self.planner.plan(self.approvals.add(dict(self.spec, sample_ids=["new"])))
        self.assertEqual(old_recipe["release_id"], base["release_id"])

    def test_unsupported_and_unapproved_do_not_reach_worker(self):
        with self.assertRaises(KeyError):
            self.planner.plan("unapproved")
        for changes in ({"experiment_type": "kinetics"}, {"verification_contract": "concentration@2"}):
            task = self.planner.plan(self.approvals.add(dict(self.spec, **changes)))
            self.assertEqual(task["state"], "unsupported")
            self.assertEqual(self.planner.run(task["id"]), task)
        self.assertEqual(self.calls, [])

    def test_worker_failure_and_explicit_retry_with_no_archive_substitution(self):
        planned = self.planner.plan(self.pin)
        def fail_worker(prompt, schema):
            self.assertEqual(self.open().get(planned["id"])["state"], "generating")
            self.assertEqual(self.open().run(planned["id"])["state"], "generating")
            raise RuntimeError("worker unavailable")
        failed = self.open(worker=fail_worker).run(planned["id"])
        self.assertEqual((failed["state"], failed["worker_receipt"]["outcome"]), ("failed", "failed"))
        self.assertIn("worker unavailable", failed["worker_receipt"]["error"])
        self.assertIsNone(failed["source_revision"])
        self.assertIsNone(failed["release_id"])
        self.assertIsNone(failed["candidate"])
        self.assertEqual(self.open().plan(self.pin), failed)
        retry = self.planner.plan(self.pin, retry_of=failed["id"])
        self.assertEqual(self.planner.run(retry["id"])["state"], "candidate_ready")
        self.assertEqual(self.planner.get(failed["id"]), failed)

    def test_candidate_retained_without_verifier_or_on_rejection(self):
        plan = self.planner.plan(self.pin)
        def wrong_recipe(prompt, schema):
            response, receipt = self.worker(prompt, schema)
            response["recipe"]["settings"]["wavelength_nm"] = 450
            return response, receipt
        ready = self.open(worker=wrong_recipe, verifier=None).run(plan["id"])
        self.assertEqual(self.open(verifier=None).verify(plan["id"]), ready)
        failed = self.planner.verify(plan["id"])
        self.assertEqual(failed["state"], "verification_failed")
        self.assertIsNone(failed["release_id"])
        self.assertEqual(failed["candidate"], ready["candidate"])
        self.assertEqual(failed["files"], ready["files"])
        self.assertEqual(len(self.calls), 1)
