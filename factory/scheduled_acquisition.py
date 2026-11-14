"""Schedule the batches of an approved time course over the single-job instrument API."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json

from .context import digest
from .experiment_store import RunStore
from .uvvis_adapter import InstrumentUnavailable
from .uvvis_contract import InstrumentError, canonical, validate_key, validate_pins


def _utc(value):
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected a UTC acquisition timestamp") from exc
    if stamp.utcoffset() != timedelta(0):
        raise ValueError("Expected a UTC acquisition timestamp")
    return stamp


def _check_times(job, *, started=True):
    start = _utc(job.get("started_at")) if started or job.get("started_at") is not None else None
    if job["status"] == "running":
        if job.get("finished_at") is not None:
            raise ValueError("Running acquisition has a finish timestamp")
    else:
        end = _utc(job.get("finished_at"))
        if start is not None and end < start:
            raise ValueError("Acquisition finished before it started")


class ScheduledAcquisition:
    """A series has a durable local identity and one keyed remote job per timepoint."""

    def __init__(self, sqlite_path, approved_acquisition, *, now=None):
        self.store = RunStore(sqlite_path)
        self.acquisition = approved_acquisition
        self.adapter = approved_acquisition.adapter
        self.now = now or (lambda: datetime.now(timezone.utc))
        with self.store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS scheduled_acquisitions (
                series_id TEXT PRIMARY KEY, spec_digest TEXT NOT NULL, body TEXT NOT NULL)""")

    def _load(self, series_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT body FROM scheduled_acquisitions WHERE series_id=?", (series_id,)).fetchone()
        if not row:
            raise KeyError(series_id)
        return json.loads(row[0])

    def _save(self, series):
        with self.store.transaction() as db:
            db.execute("UPDATE scheduled_acquisitions SET body=? WHERE series_id=?",
                       (canonical(series), series["job_id"]))

    @staticmethod
    def _id(key):
        validate_key(key)
        return "series:" + digest(key.encode())

    def lookup(self, spec_digest, key):
        series_id = self._id(key)
        try:
            series = self._load(series_id)
        except KeyError:
            return None
        if series["spec_digest"] != spec_digest:
            raise ValueError("Series submission key belongs to a different specification")
        return series_id

    def submit(self, spec, recipe, calibration, key):
        series_id = self._id(key)
        approved, _ = self.acquisition.specifications.approved(spec["sha256"])
        if (approved != spec or approved["experiment_type"] != "time_course"
                or self.acquisition.specifications.compile_recipe(spec["sha256"]) != recipe):
            raise ValueError("Time course requires the exact approved specification and compiled recipe")
        validate_pins(recipe, self.adapter.pin)
        ref = approved["calibration"]
        required = {field: recipe[field] for field in ("instrument_id", "profile_id", "profile_sha256")}
        required.update({field: recipe["settings"][field] for field in ("wavelength_nm", "path_length_mm")})
        required.update({field: ref[field] for field in ("id", "unit", "blank_id")})
        if (digest(canonical(calibration).encode()) != ref["sha256"]
                or any(calibration.get(field) != value for field, value in required.items())):
            raise ValueError("Frozen calibration differs from approved time-course settings or blank")
        schedule = approved["schedule"]
        series = dict(job_id=series_id, spec_digest=spec["sha256"], status="running",
                      started_at=None, finished_at=None, cancelled=False, points=[], **schedule)
        with self.store.transaction() as db:
            db.execute("INSERT OR IGNORE INTO scheduled_acquisitions VALUES (?,?,?)",
                       (series_id, spec["sha256"], canonical(series)))
        return self.lookup(spec["sha256"], key)

    @staticmethod
    def _status(series):
        return {k: series[k] for k in ("job_id", "status", "started_at", "finished_at")} | {
            "reading_count": sum(point["reading_count"] for point in series["points"]),
            "reason": series.get("failure_reason")}

    def _finish(self, series, state, at):
        _check_times({"status": state, "started_at": series["started_at"], "finished_at": at},
                     started=state == "completed")
        series.update(status=state, finished_at=at)
        self._save(series)

    def _point_report(self, job_id, *, cancel=False):
        read = self.adapter.cancel if cancel else self.adapter.poll
        report = read(job_id)
        if (report["job_id"] != job_id
                or report["status"] not in {"running", "completed", "cancelled", "interrupted"}):
            raise ValueError("Unexpected remote point identity or state")
        _check_times(report)
        return {k: report[k] for k in ("status", "started_at", "finished_at", "reading_count")}

    def _record_point(self, series, report):
        points = series["points"]
        last = points[-1]
        last.update(report)
        series["started_at"] = points[0]["started_at"]
        if last["status"] != "running" and (series["cancelled"] or last["status"] != "completed"
                                            or len(points) == series["point_count"]):
            self._finish(series, "cancelled" if series["cancelled"] else last["status"], last["finished_at"])
        else:
            series.update(status="running", finished_at=None)
            self._save(series)

    def _repair_timing(self, series):
        # Older workers cached terminal reports before validating their timestamps.
        # Re-read those point IDs before trusting a cached terminal or scheduling a successor.
        points = series["points"]
        last = points[-1] if points else None
        corrected = False
        for point in points:
            if point["status"] == "dispatching":
                continue  # The remote ID may have been saved before the first poll.
            try:
                _check_times(point)
            except ValueError:
                report = self._point_report(point["job_id"])
                if point is last:
                    self._record_point(series, report)
                    return True
                if report["status"] != "completed":
                    raise ValueError("An earlier scheduled point has no confirmed completion")
                point.update(report)
                corrected = True
        if corrected:
            series["started_at"] = points[0]["started_at"]
        try:
            _check_times(series, started=series["status"] == "completed")
        except ValueError:
            if not last or not last["job_id"]:
                raise  # No authoritative remote timestamp for this local termination.
            self._record_point(series, self._point_report(last["job_id"]))
            return True
        if corrected:
            self._save(series)
        return corrected

    def _advance(self, series_id, cancel):
        # Serialize remote calls for this series without holding the SQLite write lock
        # used by WO-8's own submission record. The OS releases this lock on a crash.
        with closing(self.store.lock("timecourse-" + digest(series_id.encode()), blocking=True)):
            series = self._load(series_id)
            repaired = self._repair_timing(series)
            if series["status"] != "running" or (repaired and not cancel):
                return self._status(series)
            if cancel and not series["cancelled"]:
                series["cancelled"] = True
                self._save(series)
            points = series["points"]
            new_point = False
            last = points[-1] if points else None
            if not last or last["status"] == "completed":
                if series["cancelled"]:
                    self._finish(series, "cancelled", self.now().isoformat())
                    return self._status(series)
                if last:
                    due = datetime.fromisoformat(last["started_at"]) + timedelta(seconds=series["interval_s"])
                    if self.now() < due:
                        return self._status(series)
                # Record intent before any submission. Each point keeps its key on retry.
                last = dict(job_id=None, status="dispatching", reading_count=0,
                            key=f"{series_id}-{len(points) + 1}")
                points.append(last)
                new_point = True
                self._save(series)

            if last["job_id"] is None:
                if series["cancelled"]:
                    try:
                        trace = self.acquisition.get(last["key"])
                    except KeyError:
                        # WO-8 persists its application trace before sending to the simulator.
                        self._finish(series, "cancelled", self.now().isoformat())
                        return self._status(series)
                    if not trace["job_id"]:
                        raise InstrumentUnavailable("Cancelled point awaits reconciliation of its remote identity")
                else:
                    try:
                        trace = self.acquisition.submit(series["spec_digest"], key=last["key"])
                    except InstrumentError as exc:
                        # An explicit validation rejection on the first submission cannot
                        # have produced a remote job. Ambiguous retries retain ownership.
                        if not new_point or exc.status != 422:
                            raise
                        series["failure_reason"] = str(exc)
                        self._finish(series, "interrupted", self.now().isoformat())
                        return self._status(series)
                if trace["specification_sha256"] != series["spec_digest"] or not trace["job_id"]:
                    raise ValueError("Point does not identify its approved submission")
                last["job_id"] = trace["job_id"]
                self._save(series)

            report = self._point_report(last["job_id"], cancel=series["cancelled"])
            self._record_point(series, report)
            return self._status(series)

    def poll(self, series_id):
        return self._advance(series_id, False)

    def cancel(self, series_id):
        return self._advance(series_id, True)

    def measurements(self, series_id):
        series = self._load(series_id)
        points = []
        for point in series["points"]:
            if point["job_id"]:
                data = self.adapter.measurements(point["job_id"])
                if data["job_id"] != point["job_id"] or any(r["job_id"] != data["job_id"] for r in data["records"]):
                    raise ValueError("Measurement belongs to a different remote point")
                if point["status"] == "completed" and (not data["complete"] or
                                                       len(data["records"]) != point["reading_count"]):
                    raise ValueError("Incomplete measurements for a completed point")
                points.append(data)
        return dict(job_id=series_id, complete=series["status"] == "completed", points=points,
                    records=[record for point in points for record in point["records"]])
