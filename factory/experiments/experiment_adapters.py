"""Local composition of the approval, instrument and verified-release services."""
from collections import defaultdict
from contextlib import closing
import json
import sqlite3
import time

from factory.context import digest
from factory.software.standard_calibration import fit_standards
from factory.instruments.uvvis_contract import canonical, validate_job_id, validate_pins

_PINS = ("instrument_id", "profile_id", "profile_sha256")
_OPTICS = ("wavelength_nm", "path_length_mm")


def _sha(value):
    return digest(canonical(value).encode())


def _reference(cal):
    return {"sha256": _sha(cal), "settings": {k: cal[k] for k in _OPTICS},
            **{k: cal[k] for k in ("id", "contract", "unit", "instrument_id", "profile_sha256", "blank_id")}}


class LocalExperimentBackend:
    """Each instance addresses one local instrument. The database is application-owned."""

    def __init__(self, sqlite_path, specifications, approved_acquisition, planner):
        from factory.experiments.scheduled_acquisition import ScheduledAcquisition
        self.path = sqlite_path
        self.specs = specifications
        self.acquisitions = approved_acquisition
        self.instrument = approved_acquisition.adapter
        self.series = ScheduledAcquisition(sqlite_path, approved_acquisition)
        self.planner = planner
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS run_calibrations (
                          sha256 TEXT PRIMARY KEY, payload TEXT NOT NULL)""")

            # A separate receipt preserves all previously pinned calibration digests.
            db.execute("""CREATE TABLE IF NOT EXISTS validated_standard_fits_v1 (
                          sha256 TEXT PRIMARY KEY)""")

    def _calibration(self, spec):
        ref = spec["calibration"]
        if not ref:
            return None
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("""SELECT c.payload, v.sha256 FROM run_calibrations c
                                LEFT JOIN validated_standard_fits_v1 v USING(sha256)
                                WHERE c.sha256=?""", (ref["sha256"],)).fetchone()
        if row is None:
            raise ValueError("Waiting for the approved frozen calibration")
        cal = json.loads(row[0])
        if (_reference(cal) != ref or cal["lab_id"] != spec["lab"]["lab_id"]
                or cal["project_id"] != spec["project"]["project_id"]
                or cal["profile_id"] != spec["instrument"]["profile_id"]):
            raise ValueError("Frozen calibration differs from the approved reference or project")
        if row[1] is None:
            self._revalidate_stored_fit(cal, ref)
        return cal

    def _revalidate_stored_fit(self, cal, reference):
        # Older rows only retained the standards digest. Resolve their original,
        # approved batch from the acquisition service, independently of the scheduler DB.
        job_id = cal["id"].removeprefix("cal-")
        validate_job_id(job_id)
        with closing(sqlite3.connect(self.acquisitions.sqlite_path)) as db:
            row = db.execute("SELECT submission_key FROM approved_acquisitions WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Frozen calibration requires revalidation from its original standard readings")
        trace = self.acquisitions.get(row[0])
        spec, _ = self.specs.approved(trace["specification_sha256"])
        readings = self.acquisitions.measurements(job_id)
        if (spec["experiment_type"] != "concentration" or readings["job_id"] != job_id
                or trace["request"]["blank_id"] != cal["blank_id"]):
            raise ValueError("Frozen calibration differs from its approved source job")
        # Only standards enter the fit, as when this reference was originally issued.
        rebuilt = fit_standards(self._inputs(spec, readings, None))
        if rebuilt is None or _reference(rebuilt) != reference:
            raise ValueError("Frozen calibration failed validation against the original standards")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO validated_standard_fits_v1 VALUES (?)", (reference["sha256"],))

    def inspect(self, spec_digest, instrument_id):
        gate = dict(approval=None, recipe=None, calibration_ready=False, blocker=None)
        try:
            spec, approval = self.specs.approved(spec_digest)
            gate["approval"] = approval
            recipe = self.specs.compile_recipe(spec_digest)
            validate_pins(recipe, self.instrument.pin)
            if instrument_id != recipe["instrument_id"]:
                raise ValueError("Run instrument differs from the approved recipe")
            gate["recipe"] = recipe
            self._calibration(spec)
            gate["calibration_ready"] = True
        except (KeyError, ValueError) as error:
            gate["blocker"] = str(error)
        return gate

    def prepare(self, spec_digest):
        task = self.planner.plan(spec_digest)
        # Follow a previous invocation's explicitly recorded retries after a restart.
        while task["state"] in {"failed", "interrupted", "verification_failed"}:
            task = self.planner.plan(spec_digest, retry_of=task["id"])
        while True:
            if task["state"] == "interrupted":
                task = self.planner.plan(spec_digest, retry_of=task["id"])
                continue
            if task["state"] == "pending":
                task = self.planner.run(task["id"])
            if task["state"] == "candidate_ready":
                if self.planner.verifier is None:
                    raise ValueError("Scientific release verifier is unavailable")
                task = self.planner.verify(task["id"])
            if task["state"] in {"released", "reused"} and task["release_id"]:
                self.planner.releases.load(task["release_id"])
                return task["release_id"]
            if task["state"] == "interrupted":
                continue
            if task["state"] not in {"pending", "candidate_ready", "generating", "verifying"}:
                reason = task.get("reason") or (task.get("worker_receipt") or {}).get("error")
                raise ValueError(f"Preparation {task['id']} is {task['state']}: {reason or 'no verified release'}")
            # The planner may hold its OS claim before it has persisted a state change.
            time.sleep(0.1)
            task = self.planner.get(task["id"])

    def acquire(self, spec_digest, key):
        spec, _ = self.specs.approved(spec_digest)
        cal = self._calibration(spec)
        if spec["experiment_type"] == "time_course":
            return self.series.submit(spec, self.specs.compile_recipe(spec_digest), cal, key)
        return self.acquisitions.submit(spec_digest, key=key)["job_id"]

    def lookup(self, spec_digest, key):
        spec, _ = self.specs.approved(spec_digest)
        if spec["experiment_type"] == "time_course":
            return self.series.lookup(spec_digest, key)
        try:
            trace = self.acquisitions.get(key)
        except KeyError:
            return None
        if trace["specification_sha256"] != spec_digest:
            raise ValueError("Acquisition key belongs to a different specification")
        return trace["job_id"]

    def _remote(self, job_id):
        return self.series if job_id.startswith("series:") else self.acquisitions

    def poll(self, job_id):
        return self._remote(job_id).poll(job_id)

    def cancel(self, job_id):
        return self._remote(job_id).cancel(job_id)

    def measurements(self, job_id):
        return self._remote(job_id).measurements(job_id)

    @staticmethod
    def _inputs(spec, measurements, cal):
        if measurements["complete"] is not True or not measurements["records"]:
            raise ValueError("Analysis requires complete measurements")
        samples, standards = spec["sample_ids"], spec["standards"]
        kind = spec["experiment_type"]
        settings = spec["settings"]
        points = measurements["points"] if kind == "time_course" else [measurements]
        count = spec["schedule"]["point_count"] if kind == "time_course" else 1
        if len(points) != count or len({p["job_id"] for p in points}) != count:
            raise ValueError("Incomplete or duplicated timepoints")
        if kind == "time_course" and [r for p in points for r in p["records"]] != measurements["records"]:
            raise ValueError("Retained timepoints differ from the complete readings")
        if kind == "concentration":
            if cal and cal["blank_id"] != measurements["records"][0]["blank_id"]:
                raise ValueError("Measurement blank differs from approved calibration")
            cal = {"id": "cal-" + measurements["job_id"], "contract": "absorbance-linear@1",
                   "blank_id": measurements["records"][0]["blank_id"], "unit": spec["units"]["concentration"],
                   "lab_id": spec["lab"]["lab_id"], "project_id": spec["project"]["project_id"],
                   **{k: spec["instrument"][k] for k in _PINS}, **{k: settings[k] for k in _OPTICS}}
        if cal is None:
            raise ValueError("Time course requires a frozen calibration")
        groups, known = [], []
        for point in points:
            by_sample = defaultdict(list)
            for row in point["records"]:
                if row["job_id"] != point["job_id"] or any(row[k] != cal[k] for k in (*_PINS, *_OPTICS, "blank_id")):
                    raise ValueError("Measurement job, blank or settings differ from approved acquisition")
                by_sample[row["sample_id"]].append(row)
            expected = {*samples, *(s["sample_id"] for s in standards)}
            if set(by_sample) != expected or any(
                    sorted(r["replicate"] for r in rows) != list(range(1, settings["replicates"] + 1))
                    for rows in by_sample.values()):
                raise ValueError("Missing or unexpected sample or replicate in completed acquisition")
            groups.extend({"sample_id": sid, "records": by_sample[sid]} for sid in samples)
            known.extend({"concentration": s["known_concentration"], "unit": cal["unit"],
                          "records": by_sample[s["sample_id"]]} for s in standards)
        return dict(experiment_type=kind, calibration=cal, groups=groups, standards=known)

    def _freeze(self, inputs):
        """Freeze a fit from the same public known standards used by the verified app."""
        cal = fit_standards(inputs)
        if cal is None:
            return None
        ref = _reference(cal)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO run_calibrations VALUES (?,?)", (ref["sha256"], canonical(cal)))
            saved, = db.execute("SELECT payload FROM run_calibrations WHERE sha256=?", (ref["sha256"],)).fetchone()
            if saved != canonical(cal):
                raise ValueError("Existing frozen calibration failed its digest check")
            db.execute("INSERT OR IGNORE INTO validated_standard_fits_v1 VALUES (?)", (ref["sha256"],))
        return ref

    def analyze(self, spec_digest, release_id, measurements):
        from factory.software.release_planner import _compatibility, _incompatibilities
        from factory.software.scientific_analysis import analyze_release
        spec, _ = self.specs.approved(spec_digest)
        recipe = self.specs.compile_recipe(spec_digest)
        manifest, _ = self.planner.releases.load(release_id)
        reasons = _incompatibilities(manifest, _compatibility(spec, recipe))
        if reasons:
            raise ValueError("Incompatible verified release: " + ", ".join(reasons))
        inputs = self._inputs(spec, measurements, self._calibration(spec))
        result = analyze_release(self.planner.releases, release_id, inputs)
        if spec["experiment_type"] == "concentration":
            result["calibration_reference"] = self._freeze(inputs)
        return result
