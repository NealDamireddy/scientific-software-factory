"""Check identity through the real v1 HTTP boundary, including uncertain replies."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from factory.uvvis_adapter import InstrumentUnavailable, VirtualInstrumentAdapter
from factory.uvvis_contract import InstrumentError
from factory.uvvis_http import InstrumentHandler
from tests.test_uvvis_api import Clock, PIN, SETTINGS, instrument, raw, until


IDENTITY = "uvvis-lifecycle-test"
MISMATCHES = {"instrument_id": "another-instrument", "profile_id": "virtual-uvvis@2",
              "profile_sha256": "a" * 64}


def adapter(port, **changes):
    pin = {**PIN, "instrument_id": IDENTITY, **changes}
    return VirtualInstrumentAdapter(f"http://127.0.0.1:{port}", pin["instrument_id"],
                                    pin["profile_id"], pin["profile_sha256"])


class LifecycleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.store = Path(self.enterContext(tempfile.TemporaryDirectory()))

    @contextmanager
    def live(self, **options):
        with instrument(self.store, instrument_id=IDENTITY, **options) as (service, client):
            yield service, adapter(client.port)

    def test_foreign_adapter_cannot_cancel_or_read_an_empty_job(self):
        with self.live(duration_s=60) as (_, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17"], blank, "owner")["job_id"]
            self.assertEqual(owner.measurements(job_id)["records"], [])
            for field, value in MISMATCHES.items():
                foreign = adapter(owner.port, **{field: value})
                for operation in (foreign.poll, foreign.measurements, foreign.cancel):
                    with self.subTest(field=field, operation=operation.__name__):
                        with self.assertRaisesRegex(InstrumentError, field):
                            operation(job_id)
                with self.subTest(field=field, owner_state=True):
                    self.assertEqual(owner.poll(job_id)["status"], "running")
            self.assertEqual(owner.cancel(job_id)["status"], "cancelled")

    def test_substituted_or_incomplete_job_prevents_cancel(self):
        with self.live(duration_s=60) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job = owner.submit(SETTINGS, ["vial-q17"], blank, "owner")
            job_id = job["job_id"]
            for field, value in {**MISMATCHES, "job_id": "f" * 32, "missing": None}.items():
                response = dict(job)
                if field == "missing":
                    del response["profile_id"]
                else:
                    response[field] = value
                with self.subTest(field=field), patch.object(service, "job", return_value=response):
                    for op in (owner.poll, owner.cancel):
                        with self.assertRaises(InstrumentUnavailable):
                            op(job_id)
                with self.subTest(field=field, owner_state=True):
                    self.assertEqual(owner.poll(job_id)["status"], "running")

    def test_serving_instance_changes_after_preflight(self):
        with self.live(duration_s=60) as (original, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17"], blank, "copied")["job_id"]
            path = f"/v1/acquisitions/{job_id}"
            copied = self.store / "replacement"
            copied.mkdir()
            with closing(sqlite3.connect(copied / "jobs.sqlite3")) as db:
                original.db.backup(db)

            with instrument(copied, instrument_id=IDENTITY + "-replacement") as (replacement, client):
                status, historical = raw(client, "GET", path)
                self.assertEqual(status, 200)
                self.assertEqual((historical["instrument_id"], historical["status"]), (IDENTITY, "interrupted"))
                self.assertEqual(raw(client, "GET", path + "/measurements"),
                                 (200, {"schema_version": 1, "job_id": job_id, "complete": False, "records": []}))
                route = InstrumentHandler._route
                # The same loopback origin serves A's preflight and B's final
                # request. B owns a real reopened copy of A's historical job.
                def switch_service(handler):
                    if handler.path.partition("?")[0] == target:
                        handler.server = SimpleNamespace(server_port=owner.port, instrument=replacement)
                    return route(handler)

                for target, operation in ((path, owner.poll), (path + "/measurements", owner.measurements),
                                          (path + "/cancel", owner.cancel)):
                    with self.subTest(method=operation.__name__), patch.object(InstrumentHandler, "_route", switch_service):
                        with self.assertRaises(InstrumentError) as error:
                            operation(job_id)
                        self.assertEqual(error.exception.status, 409)
                    self.assertEqual(owner.poll(job_id)["status"], "running")

    def test_owned_cancel_fails_closed_on_a_legacy_cancel_route(self):
        with self.live(duration_s=60) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17"], blank, "legacy")["job_id"]
            path = f"/v1/acquisitions/{job_id}/cancel"
            route = InstrumentHandler._route
            posts = []

            def legacy_cancel(handler):
                if handler.command == "POST":
                    posts.append(handler.path)
                    # The original v1 route matches the exact path and ignores the body.
                    if handler.path == path:
                        return 200, service.cancel(job_id)
                    raise InstrumentError("path", "unknown instrument route", 404)
                return route(handler)

            with patch.object(InstrumentHandler, "_route", legacy_cancel):
                with self.assertRaises(InstrumentError) as error:
                    owner.cancel(job_id)
            self.assertEqual(error.exception.status, 404)
            self.assertEqual(len(posts), 1)
            self.assertRegex(posts[0], rf"^{path}\?pin_sha256=[0-9a-f]{{64}}$")
            self.assertEqual(owner.poll(job_id)["status"], "running")

    def test_cancel_validates_its_returned_job(self):
        with self.live(duration_s=60) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job = owner.submit(SETTINGS, ["vial-q17"], blank, "owner")
            for field, value in {**MISMATCHES, "job_id": "f" * 32}.items():
                with self.subTest(field=field), patch.object(service, "cancel", return_value={**job, field: value}):
                    with self.assertRaises(InstrumentUnavailable):
                        owner.cancel(job["job_id"])

    def test_measurement_envelope_and_every_record_match_the_job(self):
        with self.live(duration_s=0) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17"], blank, "measure")["job_id"]
            until(lambda: owner.poll(job_id)["status"] == "completed")
            good = owner.measurements(job_id)
            self.assertEqual(len(good["records"]), SETTINGS["replicates"])
            for field, value in {**MISMATCHES, "job_id": "e" * 32,
                                 "blank_id": "other-reference", "sample_id": "another-vial"}.items():
                records = [*good["records"][:-1], {**good["records"][-1], field: value}]
                with self.subTest(field=field), patch.object(service, "measurements", return_value={**good, "records": records}):
                    with self.assertRaisesRegex(InstrumentUnavailable, field):
                        owner.measurements(job_id)
            with patch.object(service, "measurements", return_value={**good, "job_id": "d" * 32}):
                with self.assertRaisesRegex(InstrumentUnavailable, "job_id"):
                    owner.measurements(job_id)

    def test_same_size_foreign_or_duplicate_replicates_and_incomplete_sets(self):
        with self.live(duration_s=0) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17", "vial-m"], blank, "replicates")["job_id"]
            until(lambda: owner.poll(job_id)["status"] == "completed")
            good = owner.measurements(job_id)
            records = good["records"]
            self.assertEqual(len(records), 2 * SETTINGS["replicates"])
            for changed in (records[:-1], [*records[:-1], records[0]],
                            [*records[:-1], {**records[-1], "replicate": SETTINGS["replicates"] + 1}]):
                with self.subTest(count=len(changed), last=changed[-1]["replicate"]):
                    with patch.object(service, "measurements", return_value={**good, "records": changed}):
                        with self.assertRaisesRegex(InstrumentUnavailable, "replicate"):
                            owner.measurements(job_id)

    def test_foreign_blank_response_cannot_supply_a_reference(self):
        with self.live() as (service, owner):
            blank = owner.blank(SETTINGS)
            for field, value in MISMATCHES.items():
                with self.subTest(field=field), patch.object(service, "blank", return_value={**blank, field: value}):
                    with self.assertRaisesRegex(InstrumentUnavailable, field):
                        owner.blank(SETTINGS)

    def test_interrupted_partial_job_keeps_identity_across_restart_and_keyed_retry(self):
        clock = Clock(block_after=1)
        with self.live(monotonic=clock.now, wait=clock.wait) as (_, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            job_id = owner.submit(SETTINGS, ["vial-q17"], blank, "recover")["job_id"]
            until(lambda: owner.poll(job_id)["reading_count"] == 1)
            partial = owner.measurements(job_id)
            self.assertFalse(partial["complete"])
            self.assertEqual([r["job_id"] for r in partial["records"]], [job_id])
        with self.live() as (service, owner):
            self.assertEqual(owner.poll(job_id)["status"], "interrupted")
            self.assertEqual(owner.measurements(job_id), partial)
            retry = owner.submit(SETTINGS, ["vial-q17"], blank, "recover")
            self.assertEqual((retry["job_id"], retry["status"]), (job_id, "interrupted"))
            self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_keyed_submit_with_foreign_response_remains_uncertain(self):
        with self.live(duration_s=0) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            submit = service.submit
            ids = set()

            def substitute(request, key):
                accepted = submit(request, key)
                ids.add(accepted["job_id"])
                return {**accepted, "profile_sha256": "b" * 64}

            with patch.object(service, "submit", side_effect=substitute):
                with self.assertRaisesRegex(InstrumentUnavailable, "profile_sha256"):
                    owner.submit(SETTINGS, ["vial-q17"], blank, "recover")
            recovered = owner.submit(SETTINGS, ["vial-q17"], blank, "recover")
            self.assertEqual(ids, {recovered["job_id"]})
            self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_short_http_body_with_valid_json_is_uncertain(self):
        with self.live(duration_s=0) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            header = InstrumentHandler.send_header

            def overstate_length(handler, name, value):
                if name == "Content-Length" and handler.path == "/v1/acquisitions":
                    value = str(int(value) + 1)
                return header(handler, name, value)

            with patch.object(InstrumentHandler, "send_header", overstate_length):
                with self.assertRaises(InstrumentUnavailable):
                    owner.submit(SETTINGS, ["vial-q17"], blank, "short")
            job = owner.submit(SETTINGS, ["vial-q17"], blank, "short")
            self.assertEqual([r[0] for r in service.db.execute("SELECT id FROM jobs")], [job["job_id"]])

    def test_rejected_retry_after_lost_post_cannot_prove_no_acquisition(self):
        with self.live(duration_s=0) as (service, owner):
            blank = owner.blank(SETTINGS)["blank_id"]
            submit = service.submit
            attempts = []

            def lose_then_reject(request, key):
                attempts.append(key)
                if len(attempts) == 1:
                    submit(request, key)
                    raise InstrumentError("service", "reply lost after accept", 503)
                raise InstrumentError("instrument_id", "instrument busy", 409)

            with patch.object(service, "submit", side_effect=lose_then_reject):
                with self.assertRaises(InstrumentUnavailable):
                    owner.submit(SETTINGS, ["vial-q17"], blank, "ambiguous")
            self.assertEqual(attempts, ["ambiguous", "ambiguous"])
            job = owner.submit(SETTINGS, ["vial-q17"], blank, "ambiguous")
            self.assertEqual([r[0] for r in service.db.execute("SELECT id FROM jobs")], [job["job_id"]])
