"""Exercise the release handoff at two Git revisions with the WO-9 fixture worker.

Run with the project Python runtime on a host with a working offline sandbox:
    python scripts/check_wo8_wo9_handoff.py WO8_COMMIT WO9_COMMIT > report.json

The commits must exist in the local repository. A disposable clone composes their
tracked trees. A conflict, missing sandbox, failed check or unexpected reuse exits
nonzero. Fresh approvals and release IDs are recorded on every run.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def exercise(root, db_path, kind, specs, releases, lab, project):
    from factory.software.release_planner import ReleasePlanner
    from factory.software.scientific_release import verify_release
    from tests.test_specifications import save_calibration_fixture

    spec = specs.start(lab.lab_id, project.project_id, experiment_type=kind)
    if kind == "time_course":
        reference = save_calibration_fixture(db_path, spec)
        spec = specs.edit(spec["sha256"], calibration=reference, schedule={"interval_s": 2, "point_count": 3})

    def approve(draft):
        specs.approve(draft["sha256"], actor="local-handoff-check", confirmed_fields=specs.confirmation_fields(draft))

    approve(spec)
    worker_calls = 0

    def fixture_worker(prompt, schema):
        nonlocal worker_calls
        worker_calls += 1
        return {
            "source": (root / "tests/fixtures/scientific_analysis.py").read_text(),
            "recipe": specs.compile_recipe(spec["sha256"]),
            "views": {"title": kind, "metrics": spec["outputs"]},
        }, {"method": "WO-9 reference fixture"}

    planner = ReleasePlanner(specs, releases, db_path, worker=fixture_worker, verifier=verify_release)
    task = planner.plan(spec["sha256"])
    candidate = planner.run(task["id"])
    result = planner.verify(task["id"])
    checks = result.get("verification", {}).get("checks", [])
    report = {
        "experiment_type": kind,
        "approved_spec_sha256": spec["sha256"],
        "preparation": {"id": task["id"], "mode": task["mode"], "state": task["state"]},
        "candidate_state": candidate["state"],
        "result_state": result["state"],
        "release_id": result["release_id"],
        "source_revision": result["source_revision"],
        "worker_calls": worker_calls,
        "checks": [
            {k: check[k] for k in ("name", "category", "status")} if check["passed"] else check for check in checks
        ],
    }
    if (candidate["state"] != "candidate_ready" or result["state"] != "released" or not result["release_id"]
            or not checks or not all(check["passed"] and check["status"] == "passed" for check in checks)
            or worker_calls != 1):
        report.update(passed=False, reason=result.get("reason") or result.get("worker_receipt"))
        return report

    edited = specs.edit(spec["sha256"], sample_ids=["sample-other"])
    approve(edited)
    previous_calls = worker_calls
    reuse_plan = planner.plan(edited["sha256"])
    reuse = planner.run(reuse_plan["id"])
    report["sample_only_reuse"] = {
        "approved_spec_sha256": edited["sha256"], "mode": reuse["mode"], "state": reuse["state"],
        "release_id": reuse["release_id"], "source_revision": reuse["source_revision"],
        "worker_calls": worker_calls - previous_calls,
    }
    report["passed"] = (reuse["mode"] == "reuse" and reuse["state"] == "reused" and worker_calls == previous_calls
                        and reuse["release_id"] == result["release_id"]
                        and reuse["source_revision"] == candidate["source_revision"] == result["source_revision"])
    return report


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("wo8", help="WO-8 implementation commit")
    args.add_argument("wo9", help="WO-9 verifier commit")
    refs = args.parse_args()
    repo = Path(__file__).resolve().parents[1]
    commits = {name: git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
               for name, ref in vars(refs).items()}
    with TemporaryDirectory() as temp:
        root = Path(temp) / "source"
        git(repo, "clone", "--quiet", "--shared", "--no-checkout", str(repo), str(root))
        tree = git(root, "merge-tree", "--write-tree", commits["wo8"], commits["wo9"])
        git(root, "read-tree", "--reset", "-u", tree)
        sys.path.insert(0, str(root))
        from factory.lab_context.context_repository import SQLiteContextRepository
        from factory.software.release_repository import ReleaseRepository
        from factory.software.scientific_release import VERIFIER
        from factory.lab_context.specifications import ExperimentSpecificationService
        from tests.test_context_repository import load_demo

        db = Path(temp) / "application.sqlite"
        context = SQLiteContextRepository(db)
        lab, project = load_demo(context)
        specs = ExperimentSpecificationService(context, db)
        releases = ReleaseRepository(db)
        reports = [exercise(root, db, kind, specs, releases, lab, project) for kind in ("concentration", "time_course")]
        passed = all(report["passed"] for report in reports)
        print(json.dumps({
            "tested_at": datetime.now(timezone.utc).isoformat(), "commits": commits, "merged_tree": tree,
            "worker": "WO-9 tests/fixtures/scientific_analysis.py", "verifier": VERIFIER,
            "passed": passed, "experiments": reports,
        }, indent=2))
        return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
