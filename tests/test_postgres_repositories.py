"""Storage contracts against a disposable PostgreSQL instance (run.sh)."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from uuid import uuid4

from factory.context import ROOT, digest, read_json
from factory.context_repository import RevisionConflict, SQLiteContextRepository
from factory.experiment_store import RunStore
from factory.release_repository import ReleaseRepository
from tests.test_context_repository import RepositoryContract

BASE_DSN = os.environ.get("EVOLVE_TEST_POSTGRES_DSN")
AT = "2026-01-01T00:00:01+00:00"
END = "2026-01-01T00:00:03+00:00"


@contextmanager
def isolated_database():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = "wo45_" + uuid4().hex
    schema = sql.Identifier(name)
    with psycopg.connect(BASE_DSN, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            yield make_conninfo(BASE_DSN, options=f"-c search_path={name}")
        finally:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


@skipUnless(BASE_DSN, "use tests/fixtures/postgres/run.sh")
class HostedContextContract(RepositoryContract, TestCase):
    def setUp(self):
        self.dsn = self.enterContext(isolated_database())
        super().setUp()

    def open_repository(self):
        from factory.postgres import PostgresContextRepository
        return PostgresContextRepository(self.dsn)


class Instrument:
    """Instrument operations observed across hosted worker restarts."""
    def __init__(self, run, job_id="confirmed-job"):
        self.run, self.job_id = run, job_id
        self.status = "running"
        self.lookups = []
        self.dispatches = []
        self.error = None

    def acquire(self, spec, key):
        self.dispatches.append((spec, key))
        if self.error:
            raise self.error
        return self.job_id

    def lookup(self, spec, dispatch_key):
        self.lookups.append((spec, dispatch_key))
        return self.job_id

    def poll(self, jid):
        return dict(job_id=self.job_id, status=self.status, started_at=AT,
                    finished_at=None if self.status == "running" else END, reading_count=3)

    def cancel(self, jid):
        self.status = "cancelled"
        return self.poll(jid)


@skipUnless(BASE_DSN, "use tests/fixtures/postgres/run.sh")
class HostedContracts(TestCase):
    def setUp(self):
        from factory.postgres import PostgresContextRepository, PostgresReleaseRepository, PostgresRunStore
        self.dsn = self.enterContext(isolated_database())
        self.local = Path(self.enterContext(TemporaryDirectory())) / "local.sqlite"
        self.context = PostgresContextRepository(self.dsn)
        self.store = PostgresRunStore(self.dsn)
        self.release = PostgresReleaseRepository(self.dsn)

    def test_context_contract_and_optimistic_concurrency(self):
        fixture = read_json(ROOT / "fixtures/context/demo.json")
        for repo in (SQLiteContextRepository(self.local), self.context):
            lab = repo.save_lab(fixture["lab"], expected_revision=0)
            project = repo.save_project(fixture["project"], expected_revision=0)
            reopened = type(repo)(self.dsn if repo == self.context else self.local)
            revised = reopened.save_lab(dict(lab.payload, name="B"), expected_revision=1)
            self.assertEqual(reopened.get("lab", lab.lab_id, revision=1), lab)
            self.assertEqual(reopened.get("project", lab.lab_id, project_id=project.project_id), project)
            self.assertEqual((project.lab_revision, project.lab_sha256), (1, lab.sha256))
            self.assertEqual(revised.revision, 2)
            with self.assertRaises(RevisionConflict):
                repo.save_lab(lab.payload, expected_revision=1)
            with self.assertRaises(KeyError):
                repo.get("project", "elsewhere", project_id=project.project_id)
            if repo != self.context:
                expected = asdict(project)
            else:
                self.assertEqual(expected | {"revision_id": project.revision_id}, asdict(project))

        def save(name):
            try:
                return self.context.save_lab(dict(lab.payload, name=name), expected_revision=2).revision
            except RevisionConflict:
                return None
        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(save, ("C", "D")), [3, None])

    def test_ownership_rollback(self):
        lab = read_json(ROOT / "fixtures/context/demo.json")["lab"]
        self.context.save_lab(lab, expected_revision=0)
        foreign = deepcopy(lab)
        foreign["lab_id"] = foreign["instruments"][0]["lab_id"] = "other"
        with self.assertRaisesRegex(ValueError, "another lab"):
            self.context.save_lab(foreign, expected_revision=0)
        with self.assertRaises(KeyError):
            self.context.get("lab", "other")

    def test_verified_release_history_and_atomic_failure(self):
        files = {"analysis.py": b"source\n"}
        manifest = dict(context={"lab": {"lab_id": "l"}, "project": {"project_id": "p"}},
                        experiment_type="concentration", artifacts={"analysis.py": digest(files["analysis.py"])})
        args = ("l", "p", "concentration")
        for repo in (ReleaseRepository(self.local), self.release):
            rid = repo._publish_verified(manifest, files)
            self.assertEqual(repo._publish_verified(manifest, files), rid)
            self.assertEqual(repo.active(*args), rid)
            self.assertIsNone(repo.active("l", "foreign", "concentration"))
            second = repo._publish_verified(manifest | {"revision": 2}, files)
            reopened = type(repo)(self.dsn if repo == self.release else self.local)
            self.assertEqual(reopened.load(rid), (manifest, files))
            self.assertEqual(reopened.active(*args), second)
            with self.assertRaises(ValueError):
                repo._publish_verified(manifest, {"analysis.py": b"wrong"})
            self.assertEqual(repo.active(*args), second)
            if repo != self.release:
                expected = rid
            else:
                self.assertEqual(rid, expected)

    def test_run_contract_and_concurrent_retry(self):
        for repo in (RunStore(self.local), self.store):
            with ThreadPoolExecutor(4) as pool:
                ids = list(pool.map(lambda _: repo.submit("key", "spec", "i", AT), range(4)))
            rid = ids[0]
            self.assertEqual(set(ids), {rid})
            with self.assertRaises(ValueError):
                repo.submit("key", "changed", "i", AT)
            with repo.edit(rid) as run:
                run.update(analysis="running", attempts=[{"lane": "analysis"}])
            reopened = type(repo)(self.dsn if repo == self.store else self.local)
            self.assertEqual(reopened.active_ids(), [rid])
            body = reopened.get(rid)
            self.assertEqual(body.pop("dispatch_key"), "experiment-" + body.pop("run_id"))
            if repo != self.store:
                expected = body
            else:
                self.assertEqual(body, expected)

    def ready(self, rid):
        with self.store.edit(rid) as run:
            run.update(dependency=None, approval={"specification_sha256": run["spec_digest"]},
                       compiled_recipe={"instrument_id": run["instrument_id"]}, recipe="verified",
                       calibration_ready=True)

    def test_fifo_gates_skip_locked_and_independent_claimers(self):
        head = self.store.submit("a", "s1", "inst1", AT)
        tail = self.store.submit("b", "s2", "inst1", AT)
        other = self.store.submit("c", "s3", "inst2", AT)
        self.ready(tail)
        self.assertIsNone(self.store.claim())
        self.ready(head)
        self.ready(other)
        # Holding the oldest ready run cannot let its follower overtake it.
        with self.store.transaction() as locked:
            self.store.read(locked, head)
            self.assertEqual(self.store.claim()["run_id"], other)
            self.assertIsNone(self.store.claim())
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: self.store.claim(), range(8)))
        self.assertEqual([run["run_id"] for run in results if run], [head])
        self.assertEqual(self.store.get(tail)["acquisition"], "queued")

    def test_crash_after_dispatch_and_terminal_reconciliation(self):
        rid = self.store.submit("a", "s", "i", AT)
        tail = self.store.submit("b", "s2", "i", AT)
        self.ready(rid)
        self.ready(tail)
        claimed = self.store.claim()
        backend = Instrument(claimed, None)
        reopened = type(self.store)(self.dsn)
        self.assertEqual(reopened.reconcile(rid, backend)["acquisition"], "uncertain")
        self.assertIsNone(reopened.claim())
        backend.job_id = "original-job"
        running = reopened.reconcile(rid, backend)
        self.assertEqual((running["acquisition"], running["job_id"]), ("running", "original-job"))
        self.assertEqual(backend.lookups, [("s", claimed["dispatch_key"])] * 2)
        backend.job_id = "different-job"
        self.assertEqual(reopened.reconcile(rid, backend)["acquisition"], "uncertain")
        self.assertIsNone(reopened.claim())
        backend.job_id, backend.status = "original-job", "completed"
        done = reopened.reconcile(rid, backend)
        self.assertEqual((done["acquisition"], done["acquisition_elapsed_s"]), ("completed", 2))
        self.assertEqual(reopened.claim()["run_id"], tail)

    def test_cancel_after_lost_response_preserves_lease(self):
        rid = self.store.submit("a", "s", "i", AT)
        self.ready(rid)
        run = self.store.claim()
        self.store.cancel(rid, AT)
        backend = Instrument(run, None)
        self.assertEqual(self.store.reconcile(rid, backend)["acquisition"], "uncertain")
        tail = self.store.submit("b", "s2", "i", AT)
        self.ready(tail)
        self.assertIsNone(self.store.claim())
        backend.job_id = "original-job"
        final = self.store.reconcile(rid, backend)
        self.assertEqual((final["job_id"], final["acquisition"], final["cancel_requested_at"]),
                         ("original-job", "cancelled", AT))
        self.assertEqual(self.store.claim()["run_id"], tail)

    def test_worker_session_release_is_separate_from_instrument_lease(self):
        from contextlib import closing
        rid = self.store.submit("a", "s", "i", AT)
        self.ready(rid)
        with closing(self.store.lock("worker")):
            self.assertIsNone(self.store.lock("worker"))
            self.assertEqual(self.store.claim()["run_id"], rid)
        with closing(self.store.lock("worker")):
            self.assertIsNone(self.store.claim())
            self.assertEqual(self.store.get(rid)["acquisition"], "dispatching")

    def test_each_trusted_readiness_pin_and_cancelled_queued_head(self):
        rid = self.store.submit("a", "s", "i", AT)
        tail = self.store.submit("b", "s2", "i", AT)
        self.ready(tail)
        for changes in ({"approval": {"specification_sha256": "other"}}, {"recipe": "pending"},
                        {"compiled_recipe": {"instrument_id": "other"}}, {"calibration_ready": False},
                        {"dependency": "missing calibration"}):
            self.ready(rid)
            with self.store.edit(rid) as run:
                run.update(changes)
            self.assertIsNone(self.store.claim())
        self.store.cancel(rid, AT)
        self.assertEqual(self.store.get(rid)["acquisition"], "cancelled")
        self.assertEqual(self.store.claim()["run_id"], tail)

    def test_claim_rollback_and_immutable_context_rows(self):
        import psycopg
        rid = self.store.submit("a", "s", "i", AT)
        self.ready(rid)
        # Simulate a failure between inserting the lease and saving the run.
        with self.store.transaction() as db:
            db.execute("""ALTER TABLE experiment_runs ADD CONSTRAINT reject_dispatch
                CHECK (body->>'acquisition' <> 'dispatching')""")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.store.claim()
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM scheduling_leases").fetchone()["n"], 0)
            db.execute("ALTER TABLE experiment_runs DROP CONSTRAINT reject_dispatch")
        self.assertEqual(self.store.claim()["run_id"], rid)
        fixture = read_json(ROOT / "fixtures/context/demo.json")
        lab = self.context.save_lab(fixture["lab"], expected_revision=0)
        with self.assertRaisesRegex(psycopg.Error, "immutable"), self.store.transaction() as db:
            db.execute("DELETE FROM context_revisions WHERE revision_id=%s", (lab.revision_id,))
        self.assertEqual(self.context.get("lab", lab.lab_id), lab)

    def test_dispatch_rejections_and_lost_response_never_retry_uncertain_job(self):
        from factory.uvvis_contract import InstrumentError
        rid = self.store.submit("a", "s", "i", AT)
        self.ready(rid)
        backend = Instrument(self.store.get(rid))
        backend.error = InstrumentError("instrument_id", "busy", status=409)
        self.assertEqual(self.store.dispatch_next(backend)["acquisition"], "queued")
        backend.error = InstrumentError("settings", "rejected", status=422)
        self.assertEqual(self.store.dispatch_next(backend)["acquisition"], "failed")
        next_id = self.store.submit("b", "next", "i", AT)
        self.ready(next_id)
        backend.error = TimeoutError("response lost")
        self.assertEqual(self.store.dispatch_next(backend)["acquisition"], "uncertain")
        reopened = type(self.store)(self.dsn)
        self.assertIsNone(reopened.dispatch_next(backend))
        backend.status = "completed"
        result = reopened.reconcile(next_id, backend)
        self.assertEqual((result["job_id"], result["acquisition"]), (backend.job_id, "completed"))
        self.assertEqual(backend.dispatches.count(("next", result["dispatch_key"])), 1)

    def test_planner_discovers_scoped_release_history_after_reopen(self):
        from factory.release_planner import ReleasePlanner
        def planner():
            reopened = type(self.release)(self.dsn)
            return ReleasePlanner(None, reopened, self.local)
        key = dict(lab_id="l", project_id="p", experiment_type="concentration")
        self.assertEqual(planner()._verified_ids(key), [])
        def publish(lab, project, revision):
            return self.release._publish_verified(
                dict(context={"lab": {"lab_id": lab}, "project": {"project_id": project}},
                     experiment_type="concentration", revision=revision, artifacts={}), {})
        old = publish("l", "p", 1)
        new = publish("l", "p", 2)
        publish("l", "other", 1)
        publish("other", "p", 1)
        self.assertEqual(planner()._verified_ids(key), [new, old])
        publish("l", "p", 1)
        self.assertEqual(self.release.verified_ids("l", "p"), [new, old])
        self.assertEqual(planner()._verified_ids(key), [old, new])

    def test_invalid_termination_holds_lease_until_valid_terminal_time(self):
        rid = self.store.submit("a", "s", "i", AT)
        follower = self.store.submit("b", "s2", "i", AT)
        self.ready(rid)
        self.ready(follower)
        backend = Instrument(self.store.claim(), "series:original")
        for start, end in ((AT, ""), (None, "malformed"), (END, AT)):
            backend.poll = lambda jid: dict(job_id=jid, status="cancelled", started_at=start,
                                             finished_at=end, reading_count=0)
            self.assertEqual(self.store.reconcile(rid, backend)["acquisition"], "uncertain")
            self.assertIsNone(self.store.claim())
        backend.poll = lambda jid: dict(job_id=jid, status="cancelled", started_at=None,
                                         finished_at=END, reading_count=0)
        self.assertEqual(self.store.reconcile(rid, backend)["acquisition"], "cancelled")
        self.assertEqual(self.store.claim()["run_id"], follower)

    def test_concurrent_reconcilers_preserve_observation_order(self):
        from threading import Event
        rid = self.store.submit("a", "s", "i", AT)
        self.ready(rid)
        backend = Instrument(self.store.claim())
        first_poll, proceed = Event(), Event()
        def delayed_poll(jid):
            first_poll.set()
            if not proceed.wait(5):
                raise TimeoutError()
            return dict(job_id=jid, status="running", started_at=AT, finished_at=None, reading_count=1)
        other = Instrument(backend.run)
        backend.poll = delayed_poll
        with ThreadPoolExecutor(2) as pool:
            older = pool.submit(self.store.reconcile, rid, backend)
            self.assertTrue(first_poll.wait(5))
            try:
                # The same per-run session lock fences competing observers during I/O.
                self.assertIsNone(self.store.lock("reconcile:" + rid))
                newer = pool.submit(self.store.reconcile, rid, other)
            finally:
                proceed.set()
            self.assertEqual(older.result()["reading_count"], 1)
            self.assertEqual(newer.result()["reading_count"], 3)
        self.assertEqual(self.store.get(rid)["reading_count"], 3)

    def test_abrupt_worker_exit_after_remote_acceptance_preserves_original_identity(self):
        import subprocess
        import sys
        from textwrap import dedent
        rid = self.store.submit("a", "s", "i", AT)
        follower = self.store.submit("b", "s2", "i", AT)
        self.ready(rid)
        self.ready(follower)
        receipt = self.local.parent / "remote-receipt"
        worker = dedent("""
            import os, sys
            from pathlib import Path
            from factory.postgres import PostgresRunStore
            class Remote:
                def acquire(self, spec, key):
                    Path(sys.argv[1]).write_text(key)
                    os._exit(73)
            PostgresRunStore(os.environ["WORKER_DSN"]).dispatch_next(Remote())
        """)
        result = subprocess.run([sys.executable, "-c", worker, str(receipt)],
                                env=os.environ | {"WORKER_DSN": self.dsn}, timeout=15)
        self.assertEqual(result.returncode, 73)
        restarted = type(self.store)(self.dsn)
        run = restarted.get(rid)
        self.assertEqual(run["acquisition"], "dispatching")
        self.assertIsNone(run["job_id"])
        self.assertEqual(receipt.read_text(), run["dispatch_key"])
        backend = Instrument(run, "original-job")
        self.assertIsNone(restarted.dispatch_next(backend))
        backend.status = "completed"
        self.assertEqual(restarted.reconcile(rid, backend)["job_id"], "original-job")
        self.assertEqual(backend.lookups, [("s", receipt.read_text())])
        self.assertEqual(backend.dispatches, [])
        self.assertEqual(restarted.claim()["run_id"], follower)
