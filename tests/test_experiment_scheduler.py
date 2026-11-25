"""Exercise the worker boundary with a controllable remote instrument and release builder."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import multiprocessing
import tempfile
import threading
import time
import unittest
from uuid import uuid4

from factory.experiments.experiment_scheduler import ExperimentOrchestrator
from factory.instruments.uvvis_adapter import InstrumentUnavailable
from factory.instruments.uvvis_contract import InstrumentError


A = sha256(b"concentration spec").hexdigest()
B = sha256(b"time-course spec").hexdigest()
INSTRUMENT = "virtual-uvvis-1"


class Clock:
    def __init__(self):
        self.seconds = 0

    def now(self):
        return datetime(2026, 11, 14, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds


class ControlledBackend:
    def __init__(self, clock):
        self.clock = clock
        self.blockers = {}
        self.jobs = {}
        self.keys = {}
        self.submissions = []
        self.builds = []
        self.rejected_releases = set()
        self.analyses = []
        self.build_gates = defaultdict(threading.Event)
        self.analysis_gates = defaultdict(threading.Event)
        self.lost_submit = False
        self.lost_poll = False
        self.lost_cancel = False
        self.missing_id = False
        self.readings_available = True
        self.lock = threading.Lock()

    def inspect(self, spec, instrument_id):
        blocker = self.blockers.get(spec)
        return {"approval": None if blocker == "approval" else {"specification_sha256": spec},
                "recipe": None if blocker in {"approval", "recipe"} else {"instrument_id": instrument_id},
                "calibration_ready": blocker != "calibration", "blocker": blocker}

    def prepare(self, spec):
        self.builds.append(spec)
        if not self.build_gates[spec].wait(5):
            raise TimeoutError("test did not release build")
        if spec in self.rejected_releases:
            raise ValueError("release is incompatible with approved verification contract")
        return sha256(("verified:" + spec).encode()).hexdigest()

    def acquire(self, spec, key):
        with self.lock:
            self.submissions.append((spec, key))
            if key not in self.keys:
                job = uuid4().hex
                self.keys[key] = job
                self.jobs[job] = {"job_id": job, "status": "running", "reading_count": 0,
                                  "started_at": self.clock.now().isoformat(), "finished_at": None}
            if self.lost_submit:
                raise InstrumentUnavailable("response lost after durable acceptance")
            return self.keys[key]

    def poll(self, job_id):
        if self.missing_id:
            raise InstrumentError("job_id", "unknown acquisition", 404)
        if self.lost_poll:
            raise InstrumentUnavailable("instrument offline")
        return dict(self.jobs[job_id])

    def terminate(self, job_id, status="completed"):
        self.jobs[job_id].update(status=status, reading_count=2 if status == "completed" else 1,
                                 finished_at=self.clock.now().isoformat())

    def cancel(self, job_id):
        if self.lost_cancel:
            raise InstrumentUnavailable("cancel not confirmed")
        self.terminate(job_id, "cancelled")
        return self.poll(job_id)

    def measurements(self, job_id):
        if not self.readings_available:
            raise InstrumentUnavailable("measurements unavailable")
        job = self.jobs[job_id]
        return {"job_id": job_id, "complete": job["status"] == "completed",
                "records": [{"job_id": job_id, "replicate": n + 1} for n in range(job["reading_count"])]}

    def analyze(self, spec, release_id, measurements):
        if not measurements["complete"] or not measurements["records"]:
            raise AssertionError("incomplete measurements sent for analysis")
        self.analyses.append((spec, release_id, measurements["job_id"]))
        if not self.analysis_gates[spec].wait(5):
            raise TimeoutError("test did not release analysis")
        return {"job_id": measurements["job_id"], "records": len(measurements["records"])}


def build_until_process_exit(db, entered):
    """Simulate a worker dying after it has claimed a software attempt."""
    clock = Clock()
    backend = ControlledBackend(clock)
    backend.blockers[A] = "calibration"

    def prepare(spec):
        entered.set()
        threading.Event().wait(30)

    backend.prepare = prepare
    worker = ExperimentOrchestrator(db, backend, clock=clock)
    worker.submit(A, A, INSTRUMENT)
    while True:
        worker.tick()
        time.sleep(.01)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(self.enterContext(tempfile.TemporaryDirectory())) / "runs.sqlite"
        self.clock = Clock()
        self.backend = ControlledBackend(self.clock)
        self.workers = []
        self.worker = self.open()
        self.addCleanup(self.stop_workers)

    def open(self):
        worker = ExperimentOrchestrator(self.db, self.backend, clock=self.clock)
        self.workers.append(worker)
        return worker

    def stop_workers(self):
        for spec in [A, B]:
            self.backend.build_gates[spec].set()
            self.backend.analysis_gates[spec].set()
        for worker in self.workers:
            worker.close()

    def restart(self):
        self.workers.remove(self.worker)
        self.worker.close()
        self.worker = self.open()

    def submit(self, spec, key=None):
        return self.worker.submit(key or spec, spec, INSTRUMENT)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.worker.tick()
            if predicate():
                return
            time.sleep(.005)
        self.fail("worker never reached expected state")

    def job(self, run):
        self.wait_for(lambda: self.worker.status(run)["job_id"] is not None)
        return self.worker.status(run)["job_id"]

    def test_fifo_parallel_preparation_and_reuse_instrument_during_analysis(self):
        first, second = self.submit(A), self.submit(B)
        first_job = self.job(first)
        self.wait_for(lambda: set(self.backend.builds) == {A, B})
        self.assertIsNone(self.worker.status(second)["job_id"])
        self.assertTrue(self.worker.status(second)["blockers"])
        self.clock.seconds = 2
        self.backend.build_gates[A].set()
        self.wait_for(lambda: self.worker.status(first)["software"] == "ready")
        self.assertEqual(self.backend.analyses, [])
        self.clock.seconds = 5
        self.backend.terminate(first_job)
        second_job = self.job(second)
        self.wait_for(lambda: len(self.backend.analyses) == 1)
        self.assertEqual(self.backend.analyses[0][::2], (A, first_job))
        self.assertNotEqual(first_job, second_job)
        self.assertEqual([s for s, _ in self.backend.submissions], [A, B])
        status = self.worker.status(first)
        self.assertEqual(status["software_wait_s"], 0)
        self.assertEqual(status["acquisition"], "completed")
        self.assertNotEqual(status["analysis"], "completed")
        self.backend.analysis_gates[A].set()
        self.wait_for(lambda: self.worker.status(first)["analysis"] == "completed")

    def test_pending_wait_begins_at_remote_finish_and_stops_at_software_readiness(self):
        run = self.submit(A)
        job = self.job(run)
        self.wait_for(lambda: A in self.backend.builds)
        self.clock.seconds = 4
        self.backend.terminate(job)
        self.clock.seconds = 9  # Delivery of the terminal poll was delayed.
        self.wait_for(lambda: self.worker.status(run)["acquisition"] == "completed")
        status = self.worker.status(run)
        self.assertTrue(status["software_wait_pending"])
        self.assertEqual(status["software_wait_s"], 5)
        self.assertEqual(datetime.fromisoformat(status["acquisition_finished_at"]),
                         datetime.fromisoformat(self.backend.jobs[job]["finished_at"]))
        self.clock.seconds = 13
        self.backend.build_gates[A].set()
        self.wait_for(lambda: bool(self.backend.analyses))
        self.clock.seconds = 20
        self.backend.analysis_gates[A].set()
        self.wait_for(lambda: self.worker.status(run)["analysis"] == "completed")
        status = self.worker.status(run)
        self.assertEqual(status["software_wait_s"], 9)
        self.assertFalse(status["software_wait_pending"])
        for track in ("acquisition", "software", "analysis"):
            start = datetime.fromisoformat(status[track + "_started_at"])
            finish = datetime.fromisoformat(status[track + "_finished_at"])
            self.assertLessEqual(start, finish)

    def test_dependency_blockers_persist_and_calibration_allows_software_to_prepare(self):
        self.backend.blockers[A] = "approval"
        run = self.submit(A)
        for blocker in ["approval", "recipe", "calibration"]:
            self.backend.blockers[A] = blocker
            self.worker.tick()
            self.assertIn(blocker, " ".join(self.worker.status(run)["blockers"]).lower())
            self.assertFalse(self.backend.submissions)
        self.wait_for(lambda: A in self.backend.builds)
        self.backend.build_gates[A].set()
        self.wait_for(lambda: self.worker.status(run)["software"] == "ready")
        self.restart()
        self.assertIn("calibration", " ".join(self.worker.status(run)["blockers"]).lower())
        del self.backend.blockers[A]
        self.job(run)
        self.assertEqual(len(self.backend.jobs), 1)

    def test_two_workers_contend_and_submission_keys_survive_restart(self):
        other = self.open()
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        barrier = threading.Barrier(2)

        def concurrent_submit(worker):
            barrier.wait(2)
            return worker.submit("same-key", A, INSTRUMENT)

        with ThreadPoolExecutor(2) as pool:
            first, duplicate = list(pool.map(concurrent_submit, [self.worker, other]))
            self.assertEqual(first, duplicate)
            with self.assertRaises(ValueError):
                other.submit("same-key", B, INSTRUMENT)
            second = self.submit(B)
            def contention(worker):
                barrier.wait(2)
                worker.tick()

            list(pool.map(contention, [self.worker, other]))
        self.job(first)
        self.assertEqual(len(self.backend.jobs), 1)
        self.assertEqual({spec for spec, _ in self.backend.submissions}, {A})
        self.assertIsNone(other.status(second)["job_id"])
        self.assertEqual(other.submit("same-key", A, INSTRUMENT), first)

    def test_process_exit_during_post_cannot_turn_reconciliation_error_into_release(self):
        first, second = self.submit(A), self.submit(B)
        original_submit = self.backend.acquire

        def die_after_submit(spec, key):
            original_submit(spec, key)
            raise SystemExit("remote accepted before local identity was committed")

        self.backend.acquire = die_after_submit
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        with self.assertRaises(SystemExit):
            self.worker.tick()
        self.restart()

        def reject_preflight(spec, key):
            raise InstrumentError("profile_id", "live profile differs", 409)

        self.backend.acquire = reject_preflight
        self.worker.tick()
        self.assertEqual(self.worker.status(first)["acquisition"], "uncertain")
        self.assertIsNone(self.worker.status(second)["job_id"])
        self.backend.acquire = original_submit
        self.assertEqual(self.job(first), next(iter(self.backend.jobs)))
        self.assertEqual(len(self.backend.jobs), 1)

    def test_restart_with_lost_submit_recovers_original_job_and_unknown_poll_holds_lease(self):
        self.backend.lost_submit = True
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        first, second = self.submit(A), self.submit(B)
        self.wait_for(lambda: bool(self.backend.jobs))
        original, = self.backend.jobs.keys()
        self.restart()
        self.backend.lost_submit = False
        self.assertEqual(self.job(first), original)
        identifications = list(self.backend.submissions)
        self.backend.missing_id = True
        self.clock.seconds += 86400
        for _ in range(3):
            self.worker.tick()
        self.assertEqual(self.backend.submissions, identifications)
        self.assertTrue(self.worker.status(first)["blockers"])
        self.assertIsNone(self.worker.status(second)["job_id"])
        self.assertEqual(len(self.backend.keys), 1)
        self.backend.missing_id = False
        self.backend.terminate(original, "interrupted")
        self.job(second)
        self.assertFalse(self.backend.analyses)

    def test_cancellation_waits_for_remote_confirmation_and_excludes_partial_analysis(self):
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        first, second = self.submit(A), self.submit(B)
        first_job = self.job(first)
        self.backend.lost_cancel = True
        self.worker.cancel(first)
        self.worker.tick()
        self.assertEqual(self.backend.jobs[first_job]["status"], "running")
        self.restart()
        self.worker.tick()
        self.assertIsNone(self.worker.status(second)["job_id"])
        self.backend.lost_cancel = False
        self.job(second)
        self.assertEqual(self.backend.jobs[first_job]["status"], "cancelled")
        self.assertNotEqual(self.worker.status(first)["analysis"], "completed")
        self.assertFalse(self.backend.analyses)

    def test_confirmed_termination_releases_lease_before_measurements_can_be_downloaded(self):
        first, second = self.submit(A), self.submit(B)
        first_job = self.job(first)
        self.backend.terminate(first_job)
        self.backend.readings_available = False
        self.job(second)
        self.assertEqual(self.backend.analyses, [])
        self.backend.readings_available = True
        self.backend.build_gates[A].set()
        self.backend.analysis_gates[A].set()
        self.wait_for(lambda: self.worker.status(first)["analysis"] == "completed")

    def kill_preparation_worker(self):
        context = multiprocessing.get_context("spawn")
        entered = context.Event()
        child = context.Process(target=build_until_process_exit, args=(self.db, entered))
        child.start()
        try:
            self.assertTrue(entered.wait(5), "child never began its preparation attempt")
        finally:
            child.terminate()
            child.join(5)
        self.assertFalse(child.is_alive())

    def test_dead_preparation_worker_records_interruption_and_starts_new_attempt(self):
        self.kill_preparation_worker()
        self.backend.blockers[A] = "calibration"
        self.backend.build_gates[A].set()
        run = self.submit(A)
        self.wait_for(lambda: self.worker.status(run)["software"] == "ready")
        attempts = self.worker.status(run)["attempts"]
        self.assertGreaterEqual(len(attempts), 2)
        self.assertIn("interrupted", str(attempts))
        self.assertFalse(self.backend.jobs)

    def test_cancelling_queued_run_never_dispatches_its_acquisition(self):
        first, second = self.submit(A), self.submit(B)
        self.worker.cancel(first)
        self.job(second)
        self.assertEqual([spec for spec, _ in self.backend.submissions], [B])
        self.assertIsNone(self.worker.status(first)["job_id"])

    def test_incompatible_release_does_not_start_analysis_on_complete_readings(self):
        self.backend.rejected_releases.add(A)
        self.backend.build_gates[A].set()
        run = self.submit(A)
        self.backend.terminate(self.job(run))
        self.wait_for(lambda: self.worker.status(run)["acquisition"] == "completed"
                      and self.worker.status(run)["software_finished_at"] is not None)
        status = self.worker.status(run)
        self.assertNotEqual(status["software"], "ready")
        self.assertNotEqual(status["analysis"], "completed")
        self.assertIn("incompatible", str(status["blockers"]).lower())
        self.assertFalse(self.backend.analyses)

    def test_cancel_after_lost_response_never_resubmits_to_discover_identity(self):
        self.backend.lost_submit = True
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        run, second = self.submit(A), self.submit(B)
        self.wait_for(lambda: bool(self.backend.jobs))
        original, = self.backend.jobs
        before = list(self.backend.submissions)
        self.worker.cancel(run)
        self.restart()
        self.backend.lost_submit = False
        self.worker.tick()
        self.assertEqual(self.backend.submissions, before)
        self.assertTrue(self.worker.status(run)["blockers"])
        self.assertIsNone(self.worker.status(second)["job_id"])
        # Once the application recovers the trace, poll/cancel only that identity.
        self.backend.lookup = lambda spec, key: self.backend.keys.get(key)
        self.job(second)
        self.assertEqual(self.backend.jobs[original]["status"], "cancelled")

    def test_mixed_job_readings_do_not_start_analysis(self):
        self.backend.build_gates[A].set()
        self.backend.analysis_gates[A].set()
        run = self.submit(A)
        job = self.job(run)
        self.wait_for(lambda: self.worker.status(run)["software"] == "ready")
        fetch = self.backend.measurements

        def mixed(job_id):
            batch = fetch(job_id)
            batch["records"][0]["job_id"] = uuid4().hex
            return batch

        self.backend.measurements = mixed
        self.backend.terminate(job)
        self.worker.tick()
        self.assertIsNone(self.worker.status(run)["measurements"])
        self.assertTrue(self.worker.status(run)["blockers"])
        self.assertFalse(self.backend.analyses)
        self.backend.measurements = fetch
        self.wait_for(lambda: self.worker.status(run)["analysis"] == "completed")

    def test_non_json_analysis_outcome_records_failed_attempt_once(self):
        def invalid_result(spec, release_id, measurements):
            self.backend.analyses.append(spec)
            return {"estimate": float("nan")}

        self.backend.analyze = invalid_result
        self.backend.build_gates[A].set()
        run = self.submit(A)
        self.backend.terminate(self.job(run))
        self.wait_for(lambda: self.worker.status(run)["analysis"] == "failed")
        self.worker.tick()
        self.assertEqual(self.backend.analyses, [A])
        self.assertTrue(self.worker.status(run)["blockers"])

    def test_cancel_concurrent_with_definitive_busy_rejection_unblocks_fifo(self):
        first, second = self.submit(A), self.submit(B)
        acquire = self.backend.acquire

        def busy(spec, key):
            if spec == A:
                self.worker.cancel(first)
                raise InstrumentError("instrument_id", "instrument has an active acquisition", 409)
            return acquire(spec, key)

        self.backend.acquire = busy
        self.job(second)
        self.assertEqual(self.worker.status(first)["acquisition"], "cancelled")

    def test_cancel_after_process_death_closes_orphaned_build_attempt(self):
        self.kill_preparation_worker()
        run = self.submit(A)
        self.worker.cancel(run)
        self.worker.tick()
        status = self.worker.status(run)
        self.assertIn(status["software"], {"interrupted", "cancelled"})
        self.assertNotEqual(status["attempts"][-1]["state"], "running")
        self.assertFalse(self.backend.builds)
        self.assertFalse(self.backend.jobs)
