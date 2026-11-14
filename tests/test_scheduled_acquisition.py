from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from factory.context import digest
from factory.experiment_scheduler import ExperimentOrchestrator
from factory.uvvis_contract import canonical
from factory.scheduled_acquisition import ScheduledAcquisition
from factory.uvvis_adapter import InstrumentUnavailable


class PointInstrument:
    def __init__(self, now):
        self.now = now
        self.pin = {"instrument_id": "demo", "profile_id": "virtual-uvvis@1", "profile_sha256": "a" * 64}
        self.jobs = {}
        self.traces = {}
        self.specifications = self
        self.adapter = self
        self.lose_reply = False
        self.submit_calls = 0
        self.recipe = {**self.pin, "settings": {"wavelength_nm": 550, "path_length_mm": 10, "replicates": 1}}
        self.calibration = {"id": "cal-1", "unit": "mg/L", "blank_id": "frozen-blank",
                            **self.pin, "wavelength_nm": 550, "path_length_mm": 10}
        self.spec = dict(sha256="b" * 64, experiment_type="time_course", status="approved",
                         calibration=dict(self.calibration, sha256=digest(canonical(self.calibration).encode())),
                         schedule={"interval_s": 10, "point_count": 2},
                         sample_ids=["vial"], standards=[])

    def approved(self, sha):
        assert sha == self.spec["sha256"]
        return self.spec, {"specification_sha256": sha}

    def compile_recipe(self, sha):
        return self.recipe

    def get(self, key):
        return self.traces[key]

    def submit(self, sha, *, key):
        self.submit_calls += 1
        if key not in self.traces:
            jid = f"{len(self.jobs) + 1:032x}"
            self.jobs[jid] = dict(job_id=jid, status="running", started_at=self.now().isoformat(),
                                  finished_at=None, reading_count=0)
            self.traces[key] = dict(specification_sha256=sha, job_id=None)
        if self.lose_reply:
            raise InstrumentUnavailable("The submit reply was lost")
        self.traces[key]["job_id"] = list(self.jobs)[list(self.traces).index(key)]
        return self.traces[key]

    def finish(self, jid, status="completed"):
        self.jobs[jid].update(status=status, finished_at=self.now().isoformat(), reading_count=1)

    def poll(self, jid):
        return self.jobs[jid]

    def cancel(self, jid):
        self.finish(jid, "cancelled")
        return self.jobs[jid]

    def measurements(self, jid):
        return {"complete": self.jobs[jid]["status"] == "completed", "job_id": jid,
                "records": [dict(job_id=jid, sample_id="vial", replicate=1, timestamp=self.jobs[jid]["started_at"])]
                if self.jobs[jid]["reading_count"] else []}


class ScheduledAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "runs.sqlite"
        self.at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.remote = PointInstrument(lambda: self.at)
        self.service = self.open()
        self.series = self.submit()

    def open(self):
        return ScheduledAcquisition(self.path, self.remote, now=lambda: self.at)

    def submit(self):
        return self.service.submit(self.remote.spec, self.remote.recipe, self.remote.calibration, "experiment-A")

    def test_durable_schedule_uses_actual_starts_original_job_ids_and_point_order(self):
        self.assertEqual(self.submit(), self.series)
        self.assertEqual(self.remote.jobs, {})
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: self.open().poll(self.series), range(3)))
        first, = self.remote.jobs
        self.at += timedelta(seconds=2)
        self.remote.finish(first)
        self.service = self.open()
        self.assertEqual(self.service.poll(self.series)["status"], "running")
        self.service.poll(self.series)
        self.assertEqual(list(self.remote.jobs), [first])
        self.at += timedelta(seconds=15)
        self.service.poll(self.series)
        _, second = self.remote.jobs
        self.at += timedelta(seconds=1)
        self.remote.finish(second)
        job = self.service.poll(self.series)
        self.assertEqual((job["status"], job["reading_count"]), ("completed", 2))
        self.assertEqual(job["started_at"], self.remote.jobs[first]["started_at"])
        self.assertEqual(job["finished_at"], self.remote.jobs[second]["finished_at"])
        data = self.service.measurements(self.series)
        self.assertTrue(data["complete"])
        self.assertEqual([p["job_id"] for p in data["points"]], [first, second])
        self.assertEqual([r["job_id"] for r in data["records"]], [first, second])
        stamps = [datetime.fromisoformat(r["timestamp"]) for r in data["records"]]
        self.assertEqual(stamps[1] - stamps[0], timedelta(seconds=17))

    def test_cancellation_reconciles_lost_remote_identity_without_submitting(self):
        self.remote.lose_reply = True
        with self.assertRaises(InstrumentUnavailable):
            self.service.poll(self.series)
        jid, = self.remote.jobs
        self.service = self.open()
        self.assertEqual(self.service.lookup(self.remote.spec["sha256"], "experiment-A"), self.series)
        with self.assertRaisesRegex(InstrumentUnavailable, "reconciliation"):
            self.service.cancel(self.series)
        self.assertEqual(self.remote.jobs[jid]["status"], "running")
        # A separate read-only reconciliation can attach the remote ID to the saved trace.
        next(iter(self.remote.traces.values()))["job_id"] = jid
        self.assertEqual(self.service.poll(self.series)["status"], "cancelled")
        self.at += timedelta(hours=1)
        self.assertEqual(self.service.poll(self.series)["status"], "cancelled")
        self.assertFalse(self.service.measurements(self.series)["complete"])
        self.assertEqual(len(self.remote.jobs), 1)

    def test_response_lost_on_first_point_reuses_only_its_original_key(self):
        self.remote.lose_reply = True
        with self.assertRaises(InstrumentUnavailable):
            self.service.poll(self.series)
        first, = self.remote.jobs
        key, = self.remote.traces
        self.at += timedelta(minutes=2)
        self.remote.lose_reply = False
        self.remote.finish(first)
        job = self.open().poll(self.series)
        self.assertEqual(job["started_at"], self.remote.jobs[first]["started_at"])
        self.assertEqual(job["reading_count"], 1)
        self.assertEqual(list(self.remote.jobs), [first])
        self.assertEqual(list(self.remote.traces), [key])

    def test_cancel_between_points_and_mismatched_calibration(self):
        self.service.poll(self.series)
        jid, = self.remote.jobs
        self.remote.finish(jid)
        self.service.poll(self.series)
        job = self.service.cancel(self.series)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(len(self.remote.jobs), 1)
        with self.assertRaisesRegex(ValueError, "Frozen calibration"):
            self.service.submit(self.remote.spec, self.remote.recipe, dict(self.remote.calibration, blank_id="wrong"),
                                "another-run")
        self.assertIsNone(self.service.lookup(self.remote.spec["sha256"], "another-run"))

    def test_interrupted_first_point_releases_lease_only_after_valid_remote_timing(self):
        sha = self.remote.spec["sha256"]

        def worker():
            series = self.open()
            backend = SimpleNamespace(
                inspect=lambda spec, instrument: {"approval": {"specification_sha256": spec},
                    "recipe": {"instrument_id": instrument}, "calibration_ready": True, "blocker": None},
                prepare=lambda spec: "release",
                acquire=lambda spec, key: series.submit(self.remote.spec, self.remote.recipe,
                                                        self.remote.calibration, key),
                poll=series.poll)
            return closing(ExperimentOrchestrator(self.path, backend))

        def lease():
            with self.service.store.transaction() as db:
                return db.execute("SELECT run_id FROM scheduling_leases WHERE instrument='demo'").fetchone()

        with worker() as scheduler:
            run = scheduler.submit("timing", sha, "demo")
            scheduler.tick()
            first, = self.remote.jobs
            self.remote.finish(first, "interrupted")
            good = self.remote.jobs[first].copy()
            self.remote.jobs[first]["finished_at"] = None
            scheduler.tick()
            status = scheduler.status(run)
            self.assertEqual(status["acquisition"], "uncertain")
            self.assertEqual(lease(), (run,))
            sid = status["job_id"]
            cached = self.service._load(sid)
            self.assertEqual(cached["status"], "running")
            self.assertEqual(cached["points"][0]["status"], "running")
            self.assertEqual(cached["points"][0]["job_id"], first)
            self.remote.jobs[first] = good

        with worker() as restarted:
            restarted.tick()
            status = restarted.status(run)
            self.assertEqual(status["acquisition"], "interrupted")
            self.assertEqual((status["job_id"], status["acquisition_finished_at"]), (sid, good["finished_at"]))
            self.assertIsNone(lease())
            self.assertEqual(self.remote.submit_calls, 1)
            self.assertEqual(list(self.remote.jobs), [first])

    def test_legacy_terminal_repolls_known_identity_until_timestamps_are_correct(self):
        self.service.poll(self.series)
        first, = self.remote.jobs
        self.remote.finish(first, "interrupted")
        # A previous version could have committed a malformed terminal snapshot.
        cached = self.service._load(self.series)
        cached["points"][0].update(status="interrupted", finished_at=None)
        cached.update(status="interrupted", finished_at=None)
        self.service._save(cached)
        reopened = self.open()
        good = self.remote.jobs[first].copy()
        self.remote.jobs[first]["finished_at"] = None
        with self.assertRaises(ValueError):
            reopened.poll(self.series)
        self.remote.jobs[first] = good
        self.assertEqual(reopened.poll(self.series)["finished_at"], good["finished_at"])
        self.assertEqual(reopened.poll(self.series)["status"], "interrupted")
        self.assertEqual(self.remote.submit_calls, 1)

    def test_invalid_intermediate_time_never_authorizes_the_next_point(self):
        self.service.poll(self.series)
        first, = self.remote.jobs
        self.at += timedelta(seconds=12)
        self.remote.finish(first)
        good = self.remote.jobs[first].copy()
        for field, value in (("started_at", "invalid"), ("started_at", None), ("finished_at", ""),
                             ("finished_at", "2026-01-02T00:00:12"),
                             ("finished_at", "2026-01-01T23:59:59+00:00")):
            with self.subTest(field=field, value=value):
                self.remote.jobs[first] = dict(good, **{field: value})
                with self.assertRaises(ValueError):
                    self.service.poll(self.series)
                self.assertEqual(self.service._load(self.series)["points"][0]["status"], "running")
                self.assertEqual(list(self.remote.jobs), [first])
        # Resume a database written before terminal reports were validated.
        cached = self.service._load(self.series)
        cached["points"][0].update(status="completed", finished_at="")
        self.service._save(cached)
        with self.assertRaises(ValueError):
            self.open().poll(self.series)
        self.assertEqual(list(self.remote.jobs), [first])
        self.remote.jobs[first] = good
        reopened = self.open()
        reopened.poll(self.series)
        reopened.poll(self.series)
        self.assertEqual(len(self.remote.jobs), 2)
        self.assertEqual(reopened._load(self.series)["points"][0]["finished_at"], good["finished_at"])
