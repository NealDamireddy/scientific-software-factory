"""The scheduler keeps every instrument queue and every run moving to a final state."""
import unittest

from factory.instruments.uvvis_contract import InstrumentError
from tests.test_experiment_scheduler import A, B, SchedulerTests as Base


class SchedulerLivenessTests(Base):
    """Reuses the scheduler fixture and helpers; the parent's own tests are not re-run."""

    def test_blocked_head_does_not_starve_later_runs_on_the_instrument(self):
        self.backend.blockers[A] = "approval"
        blocked, ready = self.submit(A), self.submit(B)
        second_job = self.job(ready)
        self.assertIsNone(self.worker.status(blocked)["job_id"])
        self.assertIn("approval", " ".join(self.worker.status(blocked)["blockers"]).lower())
        # Once unblocked it takes the instrument as soon as the lease is free.
        del self.backend.blockers[A]
        self.worker.tick()
        self.assertIsNone(self.worker.status(blocked)["job_id"])
        self.backend.terminate(second_job)
        self.assertNotEqual(self.job(blocked), second_job)
        self.assertEqual([s for s, _ in self.backend.submissions], [B, A])

    def test_ready_runs_still_acquire_in_submission_order(self):
        first, second = self.submit(A), self.submit(B)
        acquire, attempts = self.backend.acquire, []

        def busy_once(spec, key):
            attempts.append(spec)
            if attempts == [A]:  # The instrument is briefly busy; the lease is dropped.
                raise InstrumentError("instrument_id", "instrument has an active acquisition", 409)
            return acquire(spec, key)

        self.backend.acquire = busy_once
        self.worker.tick()
        self.assertEqual(self.worker.status(first)["acquisition"], "queued")
        self.assertIsNone(self.worker.status(second)["job_id"])  # B did not jump the queue.
        self.job(first)
        self.assertEqual(attempts[:2], [A, A])

    def test_software_failure_blocks_analysis_and_retires_the_run(self):
        self.backend.rejected_releases.add(A)
        self.backend.build_gates[A].set()
        run = self.submit(A)
        self.backend.terminate(self.job(run))
        self.wait_for(lambda: self.worker.status(run)["analysis"] == "blocked")
        status = self.worker.status(run)
        self.assertEqual(status["software"], "failed")
        self.assertIn("software preparation failed", status["analysis_error"].lower())
        self.assertIn("incompatible", str(status["blockers"]).lower())
        self.assertNotIn("Waiting for a compatible verified release", status["blockers"])
        self.assertFalse(status["software_wait_pending"])
        self.assertNotIn(run, self.worker.store.active_ids())
        self.worker.tick()
        self.assertFalse(self.backend.analyses)
        self.assertEqual(len(self.backend.builds), 1)

    def test_software_failure_during_acquisition_still_finishes_and_frees_the_instrument(self):
        self.backend.rejected_releases.add(A)
        self.backend.build_gates[A].set()
        self.backend.build_gates[B].set()
        self.backend.analysis_gates[B].set()
        first, second = self.submit(A), self.submit(B)
        first_job = self.job(first)
        self.wait_for(lambda: self.worker.status(first)["software"] == "failed")
        # The acquisition is still in flight, so the run must keep being reconciled.
        self.assertEqual(self.worker.status(first)["analysis"], "pending")
        self.assertIn(first, self.worker.store.active_ids())
        self.backend.terminate(first_job)
        self.wait_for(lambda: self.worker.status(first)["analysis"] == "blocked")
        self.assertEqual(self.worker.status(first)["acquisition"], "completed")
        self.backend.terminate(self.job(second))
        self.wait_for(lambda: self.worker.status(second)["analysis"] == "completed")
        self.assertEqual([s for s, *_ in self.backend.analyses], [B])


for _name in [n for n in dir(Base) if n.startswith("test_") and n not in SchedulerLivenessTests.__dict__]:
    setattr(SchedulerLivenessTests, _name, None)  # Not callable, so unittest skips it.
del Base  # Keep discovery from collecting the parent class a second time from this module.

if __name__ == "__main__":
    unittest.main()
