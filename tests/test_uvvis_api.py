"""Contract tests for the loopback v1 instrument, independent of context persistence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import http.client
import json
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from factory.instruments.uvvis_adapter import InstrumentUnavailable, VirtualInstrumentAdapter
from factory.instruments.uvvis_contract import InstrumentError, profile_sha256
from factory.instruments.uvvis_http import make_server
from factory.instruments.uvvis_service import VirtualUvVisService


# In-memory profile loader for independent development. Production reads WO-6's registry.
PROFILE = {"schema_version": 1, "profile_id": "virtual-uvvis@1", "wavelengths_nm": [450, 550, 650],
           "path_lengths_mm": [10], "replicate_limits": {"min": 1, "max": 10},
           "operations": ["measure-absorbance"], "blank_reference_required": True, "simulated": True}
SETTINGS = {"operation": "measure-absorbance", "wavelength_nm": 650, "path_length_mm": 10, "replicates": 3}
SHA = "d441df2219b76210b43c95cbd8f57758b68d3bfb772c343e85e3af67a3d23286"
SAMPLES = {"vial-q17": {"concentration_mg_l": 7.25}, "vial-m": {"concentration_mg_l": 5, "rate_mg_l_s": 1}}
PIN = {"schema_version": 1, "instrument_id": "uvvis-demo-01", "profile_id": "virtual-uvvis@1", "profile_sha256": SHA}


@contextmanager
def instrument(store, **options):
    service = VirtualUvVisService(store, SAMPLES, profile=PROFILE, **options)
    try:
        with make_server(service) as server:
            host, port = server.server_address
            url = f"http://{host}:{port}"
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                yield service, VirtualInstrumentAdapter(url, PIN["instrument_id"], PIN["profile_id"], SHA)
            finally:
                server.shutdown()
                thread.join()
    finally:
        service.close()


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for instrument worker")
        time.sleep(0.005)


def raw(adapter, method, path, payload=None, **headers):
    conn = http.client.HTTPConnection(adapter.host, adapter.port, timeout=2)
    try:
        conn.request(method, path, json.dumps(payload), {"Content-Type": "application/json", **headers})
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


class Clock:
    def __init__(self, block_after=10):
        self.elapsed = 0
        self.block_after = block_after

    def now(self):
        return self.elapsed

    def wait(self, stop, duration):
        if self.elapsed >= self.block_after:
            stop.wait(5)
        self.elapsed += duration


class VirtualUvVisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name) / "jobs"

    def test_malformed_acceptance_reconciles_by_key(self):
        with instrument(self.store, duration_s=0) as (service, api):
            blank = api.blank(SETTINGS)["blank_id"]
            ids = []
            submit = service.submit

            def lose_identity(request, key):
                job = submit(request, key)
                ids.append(job.pop("job_id"))
                return job

            with patch.object(service, "submit", side_effect=lose_identity):
                with self.assertRaises(InstrumentUnavailable):
                    api.submit(SETTINGS, ["vial-q17"], blank, "uncertain-success")
            recovered = api.submit(SETTINGS, ["vial-q17"], blank, "uncertain-success")
            self.assertEqual(set(ids), {recovered["job_id"]})

    def test_contract_and_fresh_measurements(self):
        self.assertEqual(profile_sha256(PROFILE), SHA)
        clock = Clock()
        with instrument(self.store, duration_s=0.5, noise_sd_counts=0, monotonic=clock.now, wait=clock.wait) as (_, api):
            cap = api.capabilities()
            self.assertEqual(cap, {**PIN, "profile": PROFILE, "simulated": True})
            blank = api.blank(SETTINGS)
            samples = list(SAMPLES)
            job = api.submit(SETTINGS, samples, blank["blank_id"], "request-A")
            job_id = job["job_id"]
            until(lambda: api.poll(job_id)["status"] == "completed")
            duplicate = api.submit(SETTINGS, samples, blank["blank_id"], "request-A")
            self.assertEqual(duplicate["job_id"], job_id)
            self.assertEqual(duplicate["reading_count"], 6)
            self.assertEqual((duplicate["duration_s"], duplicate["noise_sd_counts"]), (0.5, 0))
            self.assertGreaterEqual(duplicate["finished_at"], duplicate["started_at"])
            result = api.measurements(job_id)
            self.assertTrue(result["complete"])
            records = result["records"]
            self.assertEqual([r["sample_id"] for r in records], [samples[0]] * 3 + [samples[1]] * 3)
            self.assertEqual([r["replicate"] for r in records], [1, 2, 3, 1, 2, 3])
            for n, record in enumerate(records, 1):
                self.assertEqual({k: record[k] for k in PIN}, PIN)
                self.assertEqual(record["blank_id"], blank["blank_id"])
                self.assertEqual(record["job_id"], job_id)
                self.assertEqual((record["dark_counts"], record["blank_counts"]), (blank["dark_counts"], blank["blank_counts"]))
                self.assertEqual((record["unit"], record["wavelength_nm"], record["path_length_mm"]), ("counts", 650, 10))
                self.assertEqual(record["elapsed_s"], n * 0.5)
                self.assertTrue(record["simulated"])
                self.assertEqual(record["findings"], [])
            self.assertEqual(records[0]["sample_counts"], records[2]["sample_counts"])
            self.assertGreater(records[3]["sample_counts"], records[5]["sample_counts"])
            public = json.dumps([cap, blank, job, duplicate, result])
            for private in ("concentration_mg_l", "rate_mg_l_s", "seed", "coefficient"):
                self.assertNotIn(private, public)
            with self.assertRaisesRegex(InstrumentError, "different request"):
                api.submit(SETTINGS, ["vial-m"], blank["blank_id"], "request-A")

    def test_all_channels_and_retain_invalid_counts(self):
        with instrument(self.store, duration_s=0, noise_sd_counts=0) as (service, api):
            counts = []
            for channel in PROFILE["wavelengths_nm"]:
                settings = {**SETTINGS, "wavelength_nm": channel, "replicates": 1}
                blank = api.blank(settings)
                job = api.submit(settings, ["vial-q17"], blank["blank_id"], f"channel-{channel}")
                until(lambda: api.poll(job["job_id"])["status"] == "completed")
                counts.append(api.measurements(job["job_id"])["records"][0]["sample_counts"])
            self.assertEqual(len(set(counts)), 3)
            with patch.object(service, "_detector", return_value=65535):
                job = api.submit(settings, ["vial-q17"], blank["blank_id"], "quality")
                until(lambda: api.poll(job["job_id"])["status"] == "completed")
                record = api.measurements(job["job_id"])["records"][0]
                self.assertEqual(record["sample_counts"], 65535)
                self.assertIn("Saturated detector", record["findings"])

    def test_validates_both_sides_and_reference_before_reading(self):
        with instrument(self.store, duration_s=0) as (service, api):
            blank = api.blank(SETTINGS)["blank_id"]
            for method in (api.poll, api.cancel, api.measurements):
                with self.assertRaisesRegex(InstrumentError, "job_id"):
                    method("a" * 32 + "/measurements")
            for key in ("", "contains a space", "line\nbreak", "μ"):
                with self.assertRaisesRegex(InstrumentError, "Idempotency-Key"):
                    api.submit(SETTINGS, ["vial-q17"], blank, key)
            self.assertEqual(raw(api, "POST", "/v1/acquisitions", {}, **{"Idempotency-Key": "bad key"})[0], 422)
            wrong_pin = dict(PIN)
            for field in ("instrument_id", "profile_id", "profile_sha256"):
                wrong_pin[field] = "b" * 64 if field == "profile_sha256" else "another"
                wrong = VirtualInstrumentAdapter(f"http://127.0.0.1:{api.port}", wrong_pin["instrument_id"],
                                                 wrong_pin["profile_id"], wrong_pin["profile_sha256"])
                with self.assertRaisesRegex(InstrumentError, field):
                    wrong.blank(SETTINGS)
                self.assertEqual(raw(api, "POST", "/v1/blanks", {**wrong_pin, "settings": SETTINGS})[0], 409)
                wrong_pin[field] = PIN[field]
            for setting, value in (("operation", "scan"), ("wavelength_nm", 600), ("replicates", 11),
                                   ("replicates", True), ("path_length_mm", 5)):
                settings = {**SETTINGS, setting: value}
                with self.assertRaisesRegex(InstrumentError, setting):
                    api.submit(settings, ["vial-q17"], blank, "bad")
                status, error = raw(api, "POST", "/v1/blanks", {**PIN, "settings": settings})
                self.assertEqual(status, 422)
                self.assertIn(setting, error["field"])
            request = {**PIN, "settings": SETTINGS, "sample_ids": ["vial-q17"], "blank_id": blank}
            for changes in ({"settings": {**SETTINGS, "wavelength_nm": 450}}, {"blank_id": "missing"},
                            {"sample_ids": ["invented"]}, {"blank_id": None}):
                status, _ = raw(api, "POST", "/v1/acquisitions", {**request, **changes}, **{"Idempotency-Key": "bad"})
                self.assertEqual(status, 422)
            self.assertEqual(raw(api, "POST", "/v1/acquisitions", request)[0], 422)
            self.assertEqual(raw(api, "POST", "/v1/blanks", {**PIN, "settings": SETTINGS}, Origin="http://elsewhere")[0], 403)
            self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
            self.assertEqual(service.db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 0)
            service.capabilities = {**service.capabilities, "profile": {**PROFILE, "wavelengths_nm": [600]}}
            with self.assertRaisesRegex(InstrumentError, "projection"):
                api.blank(SETTINGS)

    def test_concurrent_starts_cancel_and_reopen(self):
        clock = Clock(block_after=1)
        with instrument(self.store, monotonic=clock.now, wait=clock.wait) as (_, api):
            blank = api.blank(SETTINGS)["blank_id"]
            barrier = threading.Barrier(2)
            def start(key):
                barrier.wait()
                try:
                    return api.submit(SETTINGS, ["vial-q17"], blank, key)
                except InstrumentError as error:
                    return error
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(start, ("A", "B")))
            self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
            job_id = next(r["job_id"] for r in results if isinstance(r, dict))
            self.assertEqual(next(r.status for r in results if isinstance(r, InstrumentError)), 409)
            until(lambda: api.poll(job_id)["reading_count"] == 1)
            with self.assertRaisesRegex(InstrumentError, "active acquisition"):
                api.blank(SETTINGS)
            with self.assertRaises(BlockingIOError):
                VirtualUvVisService(self.store, SAMPLES, profile=PROFILE)
            self.assertEqual(api.cancel(job_id)["status"], "cancelled")
            self.assertEqual(api.cancel(job_id)["status"], "cancelled")
            partial = api.measurements(job_id)
            self.assertFalse(partial["complete"])
            self.assertEqual(len(partial["records"]), 1)
        with instrument(self.store) as (_, reopened):
            self.assertEqual(reopened.poll(job_id)["status"], "cancelled")
            self.assertEqual(reopened.measurements(job_id), partial)

    def test_same_instrument_excludes_second_process_with_different_store(self):
        samples = Path(self.temp.name) / "samples.json"
        samples.write_text(json.dumps(SAMPLES))
        args = [sys.executable, "-m", "factory.instruments.uvvis_http", "--store", str(self.store),
                "--samples", str(samples), "--port", "0", "--duration", "60"]
        with subprocess.Popen(args, stdout=subprocess.PIPE, text=True) as owner:
            try:
                # Cold HTTP server startup on hosted macOS can exceed 30 seconds.
                self.assertTrue(select.select([owner.stdout], [], [], 90)[0], "simulator startup timed out")
                url = owner.stdout.readline().strip()
                api = VirtualInstrumentAdapter(url, PIN["instrument_id"], PIN["profile_id"], SHA)
                blank = api.blank(SETTINGS)
                job = api.submit(SETTINGS, ["vial-q17"], blank["blank_id"], "owner")

                other_store = Path(self.temp.name) / "other-jobs"
                with self.assertRaisesRegex(BlockingIOError, PIN["instrument_id"]):
                    with closing(VirtualUvVisService(other_store, SAMPLES)):
                        pass
                with closing(VirtualUvVisService(other_store, SAMPLES, instrument_id="another-instance")):
                    self.assertEqual(api.poll(job["job_id"])["status"], "running")
            finally:
                owner.kill()
        # The kernel releases the instance identity on abrupt process exit.
        with instrument(other_store, duration_s=0) as (_, replacement):
            blank = replacement.blank(SETTINGS)
            job = replacement.submit(SETTINGS, ["vial-q17"], blank["blank_id"], "replacement")
            until(lambda: replacement.poll(job["job_id"])["status"] == "completed")

    def test_equivalent_replicate_counts_reuse_one_job_across_restart(self):
        float_settings = {**SETTINGS, "replicates": 3.0}
        with instrument(self.store, duration_s=0) as (_, api):
            blank = api.blank(float_settings)["blank_id"]
            job = api.submit(float_settings, ["vial-q17"], blank, "numeric-retry")
            until(lambda: api.poll(job["job_id"])["status"] == "completed")
            records = api.measurements(job["job_id"])["records"]
            self.assertEqual(len(records), 3)
            retry = api.submit(SETTINGS, ["vial-q17"], blank, "numeric-retry")
            self.assertEqual(retry["job_id"], job["job_id"])
            self.assertIs(type(retry["settings"]["replicates"]), int)

        # Earlier versions wrote the original JSON representation to this column.
        with closing(sqlite3.connect(self.store / "jobs.sqlite3")) as db, db:
            saved_request = json.loads(db.execute("SELECT request FROM jobs").fetchone()[0])
            saved_request["settings"]["replicates"] = 3.0
            db.execute("UPDATE jobs SET request=? WHERE id=?", (json.dumps(saved_request), job["job_id"]))
        with instrument(self.store, duration_s=0) as (service, api):
            retry = api.submit(SETTINGS, ["vial-q17"], blank, "numeric-retry")
            self.assertEqual(retry["job_id"], job["job_id"])
            self.assertEqual(api.measurements(retry["job_id"])["records"], records)
            with self.assertRaisesRegex(InstrumentError, "different request"):
                api.submit({**SETTINGS, "replicates": 2}, ["vial-q17"], blank, "numeric-retry")
            self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_reconcile_crash_snapshot_and_idempotent_retry(self):
        clock = Clock(block_after=1)
        backup = Path(self.temp.name) / "crash"
        backup.mkdir()
        with instrument(self.store, monotonic=clock.now, wait=clock.wait) as (service, api):
            blank = api.blank(SETTINGS)["blank_id"]
            job = api.submit(SETTINGS, ["vial-m"], blank, "known-key")
            until(lambda: api.poll(job["job_id"])["reading_count"] == 1)
            with service.lock:
                with sqlite3.connect(backup / "jobs.sqlite3") as snapshot:
                    service.db.backup(snapshot)
        with instrument(backup) as (_, reopened):
            same = reopened.submit(SETTINGS, ["vial-m"], blank, "known-key")
            self.assertEqual((same["job_id"], same["status"]), (job["job_id"], "interrupted"))
            self.assertFalse(reopened.measurements(same["job_id"])["complete"])
            self.assertEqual(same["reading_count"], 1)
            self.assertNotEqual(reopened.submit(SETTINGS, ["vial-m"], blank, "new-key")["job_id"], same["job_id"])

    def test_lost_response_retries_only_keyed_write(self):
        with instrument(self.store, duration_s=0) as (service, api):
            getresponse = http.client.HTTPConnection.getresponse
            calls = []
            def lose_first_post(conn):
                response = getresponse(conn)
                if response.status in (201, 202):
                    calls.append(response.status)
                    if len(calls) == 1:
                        response.close()
                        raise ConnectionResetError
                return response
            with patch.object(http.client.HTTPConnection, "getresponse", lose_first_post):
                with self.assertRaises(InstrumentUnavailable):
                    api.blank(SETTINGS)
                self.assertEqual(calls, [201])
                blank = api.blank(SETTINGS)
                calls.clear()
                job = api.submit(SETTINGS, ["vial-m"], blank["blank_id"], "lost")
                self.assertEqual(calls, [202, 202])
                until(lambda: api.poll(job["job_id"])["status"] == "completed")
                self.assertEqual(api.poll(job["job_id"])["reading_count"], 3)
                self.assertEqual(service.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        with self.assertRaises(InstrumentUnavailable):
            api.capabilities()
