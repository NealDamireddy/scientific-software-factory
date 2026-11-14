"""Durable local orchestration of serial acquisitions and independent software work."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import time

from .experiment_store import RunStore
from .uvvis_contract import InstrumentError, canonical, validate_key


class SystemClock:
    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    monotonic = staticmethod(time.monotonic)


def seconds(end, start):
    return max(0., (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def reason(exc):
    return f"{type(exc).__name__}: {exc}"[:500]


TERMINAL = {"completed", "cancelled", "interrupted", "failed"}


class ExperimentOrchestrator:
    """Call tick periodically, or serve(stop_event) in a local worker process.

    All processes using the same application database must share its lock directory.
    Never point the scheduler at the simulator store. Blocking build/analysis functions
    run outside the ticking thread, with per-attempt locks released by the OS on crash.
    """
    def __init__(self, db_path, backend, *, clock=None):
        self.store = RunStore(db_path)
        self.backend = backend
        self.clock = clock or SystemClock()
        self.pools = {lane: ThreadPoolExecutor(max_workers=4, thread_name_prefix=lane)
                      for lane in ("software", "analysis")}

    def _now(self):
        return self.clock.now().astimezone(timezone.utc).isoformat()

    def submit(self, key, spec_digest, instrument_id):
        validate_key(key)
        if not spec_digest or not instrument_id:
            raise ValueError("A specification digest and instrument identity are required")
        return self.store.submit(key, spec_digest, instrument_id, self._now())

    def cancel(self, run_id):
        with self.store.edit(run_id) as run:
            if run["analysis"] == "completed" or run["cancel_requested_at"]:
                return
            run["cancel_requested_at"] = self._now()
            if run["acquisition"] == "queued":
                run["acquisition"] = "cancelled"
            for lane in ("software", "analysis"):
                if run[lane] == "pending":
                    run[lane] = "cancelled"

    def status(self, run_id):
        run = self.store.get(run_id)
        blockers = [r for r in [run["dependency"], *(run[l+"_error"] for l in
                    ("acquisition", "software", "analysis"))] if r]
        if run["acquisition"] == "queued" and not run["dependency"]:
            blockers.append("Waiting for FIFO instrument lease")
        end = run["acquisition_finished_at"]
        pending = False
        wait = None
        if run["acquisition"] == "completed":
            ready = run["software_finished_at"] if run["software"] == "ready" else None
            stop = ready or run["cancel_requested_at"]
            pending = stop is None
            wait = seconds(stop or self._now(), end)
            if not ready and not run["cancel_requested_at"]:
                blockers.append("Waiting for a compatible verified release")
        return dict(run, blockers=blockers, software_wait_s=wait, software_wait_pending=pending)

    def serve(self, stop, *, interval=.1):
        while not stop.is_set():
            self.tick()
            stop.wait(interval)

    def close(self):
        for pool in self.pools.values():
            pool.shutdown(wait=True)

    def tick(self):
        # Only one dispatcher issues remote commands at a time. Submit/inspect,
        # cancellation intent and background workers do not wait for instrument I/O.
        lock = self.store.lock("dispatcher")
        if lock is None:
            return
        with closing(lock):
            for rid in self.store.active_ids():
                self._advance(rid)

    def _advance(self, rid):
        run = self.store.get(rid)
        if (run["cancel_requested_at"] or run["acquisition"] in {"cancelled", "interrupted", "failed"}):
            self._retire_abandoned_work(run)
        if (run["analysis"] in {"completed", "failed"} or
                run["acquisition"] in {"cancelled", "interrupted", "failed"}):
            return
        if not run["cancel_requested_at"]:
            self._inspect(run)
            self._schedule(rid, "software")
        run = self.store.get(rid)
        if run["acquisition"] == "queued" and not run["dependency"]:
            self._claim(rid)
        run = self.store.get(rid)
        if run["acquisition"] in {"dispatching", "uncertain", "running"}:
            self._reconcile(run)
        run = self.store.get(rid)
        if run["acquisition"] == "completed" and not run["cancel_requested_at"]:
            if run["measurements"] is None:
                self._read_measurements(run)
            self._schedule(rid, "analysis")

    def _retire_abandoned_work(self, run):
        for lane in ("software", "analysis"):
            if run[lane] != "running":
                continue
            lock = self.store.lock(run["run_id"] + "-" + lane)
            if lock is None:
                continue  # The live worker records its own finish.
            with closing(lock), self.store.edit(run["run_id"]) as current:
                if current[lane] == "running":
                    last = next(a for a in reversed(current["attempts"]) if a["lane"] == lane)
                    last.update(state="interrupted", detected_at=self._now())
                    current[lane] = "cancelled" if current["cancel_requested_at"] else "interrupted"
                    current[lane+"_error"] = "Worker exited before recording an outcome"

    def _inspect(self, run):
        # The readiness adapter reads trusted repositories, never caller-supplied flags.
        try:
            info = self.backend.inspect(run["spec_digest"], run["instrument_id"])
            approval, recipe = info["approval"], info["recipe"]
            if approval and approval["specification_sha256"] != run["spec_digest"]:
                raise ValueError("Approval does not match specification")
            if recipe and recipe["instrument_id"] != run["instrument_id"]:
                raise ValueError("Recipe does not match instrument")
            calibration = info["calibration_ready"] is True
            blocker = (info["blocker"] or (not approval and "Specification requires approval")
                       or (not recipe and "Acquisition recipe is unverified")
                       or (not calibration and "Required calibration is unavailable") or None)
        except Exception as exc:
            approval, recipe, calibration, blocker = None, None, False, reason(exc)
        with self.store.edit(run["run_id"]) as current:
            current.update(approval=approval, recipe="verified" if recipe and approval else "pending",
                           compiled_recipe=recipe, calibration_ready=calibration, dependency=blocker)

    def _claim(self, rid):
        with self.store.transaction() as db:
            run = self.store.read(db, rid)
            instrument = run["instrument_id"]
            head = db.execute("""SELECT run_id FROM experiment_runs WHERE instrument=?
                AND json_extract(body,'$.acquisition')='queued' ORDER BY seq LIMIT 1""", (instrument,)).fetchone()
            if head != (rid,) or run["cancel_requested_at"] or run["dependency"]:
                return
            lease = db.execute("INSERT OR IGNORE INTO scheduling_leases VALUES (?,?)", (instrument, rid))
            if lease.rowcount:
                run["acquisition"] = "dispatching"
                self.store.save(db, run)

    def _reconcile(self, run):
        rid, jid = run["run_id"], run["job_id"]
        first_dispatch = False
        try:
            if not jid:
                # Commit intent before the call. A process may die after the POST
                # but before it saves either the returned identity or an error.
                with self.store.transaction() as db:
                    current = self.store.read(db, rid)
                    cancelled = current["cancel_requested_at"]
                    if not current.get("dispatch_attempted"):
                        if cancelled:
                            current["acquisition"] = "cancelled"
                            db.execute("DELETE FROM scheduling_leases WHERE run_id=?", (rid,))
                        else:
                            current["dispatch_attempted"] = first_dispatch = True
                        self.store.save(db, current)
                        if cancelled:
                            return
                if cancelled:
                    # A lost POST response cannot justify creating work after cancellation.
                    lookup = getattr(self.backend, "lookup", None)
                    jid = lookup(run["spec_digest"], run["dispatch_key"]) if lookup else None
                    if not jid:
                        raise RuntimeError("Cancelled dispatch has no confirmed remote identity; lease retained")
                else:
                    jid = self.backend.acquire(run["spec_digest"], run["dispatch_key"])
                if not isinstance(jid, str) or not jid:
                    raise ValueError("Missing acquisition identity")
                with self.store.edit(rid) as current:
                    current["job_id"] = jid
            cancelled = self.store.get(rid)["cancel_requested_at"]
            job = self.backend.cancel(jid) if cancelled else self.backend.poll(jid)
            state = job["status"]
            if job["job_id"] != jid or state not in {"running", "completed", "interrupted", "cancelled"}:
                raise ValueError("Unrecognized remote acquisition identity or status")
            if state != "running" and not job["finished_at"]:
                raise ValueError("Missing remote termination timestamp")
            duration = (seconds(job["finished_at"], job["started_at"])
                        if job["finished_at"] and job["started_at"] else None)
            with self.store.transaction() as db:
                current = self.store.read(db, rid)
                current.update(acquisition=state, acquisition_started_at=job["started_at"],
                               acquisition_finished_at=job["finished_at"], acquisition_elapsed_s=duration,
                               reading_count=job["reading_count"], acquisition_error=None)
                if state in TERMINAL:
                    db.execute("DELETE FROM scheduling_leases WHERE run_id=?", (rid,))
                    if state != "completed":
                        current.update(analysis="cancelled" if state == "cancelled" else "blocked",
                                       acquisition_error="Acquisition " + state)
                self.store.save(db, current)
        except InstrumentError as exc:
            # Explicit rejection of a new keyed POST means it did not start a job.
            # A conflict with the idempotency key itself, or an error polling a
            # known job, is ambiguous: keep ownership for reconciliation.
            if (first_dispatch and not jid and exc.status in (422, 409)
                    and exc.field != "Idempotency-Key"):
                with self.store.transaction() as db:
                    current = self.store.read(db, rid)
                    busy = exc.status == 409 and exc.field == "instrument_id"
                    state = "cancelled" if current["cancel_requested_at"] else "queued" if busy else "failed"
                    current.update(acquisition=state, acquisition_error=reason(exc), dispatch_attempted=False)
                    if state == "failed":
                        current["analysis"] = "blocked"
                    db.execute("DELETE FROM scheduling_leases WHERE run_id=?", (rid,))
                    self.store.save(db, current)
            else:
                self._uncertain(rid, exc)
        except Exception as exc:
            self._uncertain(rid, exc)

    def _uncertain(self, rid, exc):
        with self.store.edit(rid) as current:
            current.update(acquisition="uncertain", acquisition_error=reason(exc))

    def _read_measurements(self, run):
        try:
            data = self.backend.measurements(run["job_id"])
            if (data["job_id"] != run["job_id"] or data["complete"] is not True or
                    not data["records"] or len(data["records"]) != run["reading_count"]):
                raise ValueError("Complete readings for the terminal job are unavailable")
            if run["job_id"].startswith("series:"):
                points = data["points"]
                if (not points or len({p["job_id"] for p in points}) != len(points)
                        or any(not p["records"] or any(r["job_id"] != p["job_id"] for r in p["records"])
                               for p in points)
                        or [r for p in points for r in p["records"]] != data["records"]):
                    raise ValueError("Series readings do not match the remote timepoint jobs")
            elif any(r["job_id"] != run["job_id"] for r in data["records"]):
                raise ValueError("Readings do not belong to the completed acquisition")
            with self.store.edit(run["run_id"]) as current:
                current.update(measurements=data, acquisition_error=None)
        except Exception as exc:
            with self.store.edit(run["run_id"]) as current:
                current["acquisition_error"] = reason(exc)

    @staticmethod
    def _eligible(run, lane):
        if run["cancel_requested_at"] or not run["approval"] or run["recipe"] != "verified":
            return False
        if lane == "software":
            return True  # Software can prepare against the calibration schema before the fit exists.
        return (not run["dependency"] and run["acquisition"] == "completed"
                and run["measurements"] is not None and run["software"] == "ready")

    def _schedule(self, rid, lane):
        run = self.store.get(rid)
        if run[lane] not in {"pending", "running"} or not self._eligible(run, lane):
            return
        lock = self.store.lock(rid + "-" + lane)
        if lock is None:
            return  # Another live thread/process is responsible for this attempt.
        try:
            self.pools[lane].submit(self._work, rid, lane, lock)
        except BaseException:
            lock.close()
            raise

    def _work(self, rid, lane, lock):
        with closing(lock):
            with self.store.edit(rid) as run:
                if run[lane] not in {"pending", "running"} or not self._eligible(run, lane):
                    return
                now = self._now()
                if run[lane] == "running":
                    last = next(a for a in reversed(run["attempts"]) if a["lane"] == lane)
                    last.update(state="interrupted", detected_at=now)
                attempt = dict(lane=lane, started_at=now, state="running")
                run["attempts"].append(attempt)
                run[lane] = "running"
                run[lane+"_started_at"] = now
                index = len(run["attempts"]) - 1
            start = self.clock.monotonic()
            try:
                if lane == "software":
                    value = self.backend.prepare(run["spec_digest"])
                    if not isinstance(value, str) or not value:
                        raise ValueError("Preparation did not yield a verified release")
                else:
                    value = self.backend.analyze(run["spec_digest"], run["release_id"], run["measurements"])
                    if not isinstance(value, dict):
                        raise ValueError("Expected an analysis outcome")
                    canonical(value)  # Only persist a finite JSON result.
                error = None
            except Exception as exc:
                value, error = None, reason(exc)
            elapsed = max(0., self.clock.monotonic() - start)
            with self.store.edit(rid) as current:
                now = self._now()
                state = ("cancelled" if current["cancel_requested_at"] else "failed" if error
                         else "ready" if lane == "software" else "completed")
                current["attempts"][index].update(state=state, finished_at=now, elapsed_s=elapsed, error=error)
                current.update({lane: state, lane+"_finished_at": now, lane+"_elapsed_s": elapsed, lane+"_error": error})
                if state in {"ready", "completed"}:
                    current["release_id" if lane == "software" else "result"] = value
