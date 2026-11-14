"""Run an approved two-experiment rehearsal in an empty, retained store."""
from contextlib import closing
import argparse
import json
from pathlib import Path
from threading import Thread
import time
from factory.context import ROOT, read_json
from factory.context_repository import SQLiteContextRepository
from factory.experiment_adapters import LocalExperimentBackend
from factory.experiment_scheduler import ExperimentOrchestrator
from factory.approved_acquisition import ApprovedAcquisition
from factory.release_planner import ReleasePlanner
from factory.release_repository import ReleaseRepository
from factory.scientific_release import verify_release
from factory.specifications import ExperimentSpecificationService
from factory.uvvis_adapter import VirtualInstrumentAdapter
from factory.uvvis_http import make_server
from factory.uvvis_service import VirtualUvVisService

def finish(scheduler, specs, spec, root):
    kind = spec["experiment_type"]
    specs.approve(spec["sha256"], actor="integration-rehearsal", confirmed_fields=specs.confirmation_fields(spec))
    rid = scheduler.submit(kind, spec["sha256"], spec["instrument"]["instrument_id"])
    deadline = time.monotonic() + 300
    while True:
        scheduler.tick()
        run = scheduler.status(rid)
        if run["analysis"] == "completed" or "failed" in (run["acquisition"], run["analysis"], run["software"]) or time.monotonic() > deadline:
            (root / (kind + ".json")).write_text(json.dumps(run, indent=2))
            print(kind, rid, run["analysis"], run["blockers"], flush=True)
            if run["analysis"] != "completed":
                raise RuntimeError("Fresh experiment failed; inspect retained evidence")
            return run
        time.sleep(.2)

def main(root):
    root.mkdir(parents=True, exist_ok=False)
    app = root / "application.sqlite"
    repo = SQLiteContextRepository(app)
    demo = read_json(ROOT / "fixtures/context/demo.json")
    lab = repo.save_lab(demo["lab"], expected_revision=0)
    project = repo.save_project(demo["project"], expected_revision=0)
    specs = ExperimentSpecificationService(repo, app)
    first = specs.start(lab.lab_id, project.project_id)
    models = {s["sample_id"]: {"concentration_mg_l": s["known_concentration"]} for s in first["standards"]}
    models.update({sample: {"concentration_mg_l": 6.25} for sample in first["sample_ids"]})
    pin = first["instrument"]
    with closing(VirtualUvVisService(root / "instrument", models, duration_s=.05)) as instrument, make_server(instrument) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            adapter = VirtualInstrumentAdapter(f"http://127.0.0.1:{server.server_port}", pin["instrument_id"], pin["profile_id"], pin["profile_sha256"])
            releases = ReleaseRepository(root / "releases.sqlite")
            planner = ReleasePlanner(specs, releases, app, verifier=verify_release)
            backend = LocalExperimentBackend(app, specs, ApprovedAcquisition(specs, app, adapter), planner)
            with closing(ExperimentOrchestrator(app, backend)) as scheduler:
                conc = finish(scheduler, specs, first, root)
                cal = conc["result"]["calibration_reference"]
                spec = specs.start(lab.lab_id, project.project_id, experiment_type="time_course")
                series = finish(scheduler, specs, specs.edit(spec["sha256"], calibration=cal, schedule={"point_count":2, "interval_s":1}), root)
                if series["result"]["calibration_id"] != cal["id"]:
                    raise ValueError("Time course lost the concentration calibration")
                points = series["measurements"]["points"]
                if len(points) != 2 or len({point["job_id"] for point in points}) != 2:
                    raise ValueError("Expected two distinct time-course acquisitions")
                for run in [conc, series]:
                    manifest, _ = releases.load(run["release_id"])
                    if manifest["worker_receipt"]["method"] != "codex exec":
                        raise ValueError("Missing live worker receipt")
                    if not manifest["checks"] or not all(c["passed"] for c in manifest["checks"]):
                        raise ValueError("Release has incomplete verification")
                    results = run["result"]["results"]
                    if not results or any(r["concentration_mg_l"] is None for r in results):
                        raise ValueError("Experiment withheld its concentration result")
        finally:
            server.shutdown()
            thread.join()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path, help="New directory for this run and its evidence")
    main(parser.parse_args().store)
