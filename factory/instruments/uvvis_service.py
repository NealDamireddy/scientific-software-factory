"""Private virtual detector, compatible references and crash-recoverable acquisitions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import sqlite3
import stat
import threading
import time
import uuid

from factory.assays.b12.optics import ADC_MAX, BLANK_COUNTS, DARK_COUNTS, DEFAULT_NOISE_COUNTS, absorbance
from factory.instruments.uvvis_contract import (
    InstrumentError, canonical, load_profile, profile_sha256, validate, validate_key, validate_pins, validate_settings,
)

# Synthetic attenuation (L/mg at 10 mm). These are discrete fixture channels.
_COEFFICIENT = {450: 0.014, 550: 0.009, 650: 0.004}
_MODEL_REVISION = "synthetic-visible@1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _private_models(samples):
    if not isinstance(samples, dict) or not samples:
        raise ValueError("The private model file requires at least one sample")
    models = {}
    for sample_id, model in samples.items():
        validate("id", sample_id)
        if not isinstance(model, dict) or model.keys() - {"concentration_mg_l", "rate_mg_l_s"}:
            raise ValueError("Invalid private sample model")
        concentration, rate = model.get("concentration_mg_l"), model.get("rate_mg_l_s", 0)
        if not _finite(concentration) or concentration < 0 or not _finite(rate):
            raise ValueError("Invalid private concentration or rate")
        models[sample_id] = (concentration, rate)
    return models


def _claim_instrument(instrument_id, resources):
    # All local processes use the same inode, independent of store, port or TMPDIR.
    # Leave the file in place: unlinking a locked inode permits a second owner.
    identity = hashlib.sha256(instrument_id.encode("utf-8")).hexdigest()
    path = Path("/tmp") / f"evolve-uvvis-instance-{identity}.lock"
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o444)
        except FileExistsError:
            fd = os.open(path, flags)
    resources.callback(os.close, fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise OSError(f"Expected a regular instrument lock file at {path}")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise BlockingIOError(f"Instrument {instrument_id!r} is already in use") from error


class VirtualUvVisService:
    def __init__(self, store, samples, *, profile=None, instrument_id="uvvis-demo-01",
                 noise_sd_counts=DEFAULT_NOISE_COUNTS, duration_s=1, seed=None,
                 monotonic=time.monotonic, wait=threading.Event.wait):
        if not _finite(noise_sd_counts) or not 0 <= noise_sd_counts <= 100:
            raise ValueError("noise_sd_counts must be between 0 and 100")
        if not _finite(duration_s) or not 0 <= duration_s <= 60:
            raise ValueError("duration_s must be between 0 and 60")
        profile = load_profile() if profile is None else profile
        self.pin = {"schema_version": 1, "instrument_id": instrument_id, "profile_id": profile["profile_id"],
                    "profile_sha256": profile_sha256(profile)}
        self.capabilities = {**self.pin, "profile": profile, "simulated": True}
        validate("capabilities", self.capabilities)
        self.samples = _private_models(samples)
        self.rng = random.Random(seed)
        self.noise = noise_sd_counts
        self.duration = duration_s
        self.monotonic = monotonic
        self.wait = wait
        self.lock = threading.RLock()
        self.stopping = False
        self.active = {}
        store = Path(store)
        store.mkdir(mode=0o700, parents=True, exist_ok=True)
        with ExitStack() as resources:
            _claim_instrument(instrument_id, resources)
            # Keep a separate store lease so another identity cannot reconcile our live jobs.
            store_lock = resources.enter_context((store / "instrument.lock").open("a"))
            fcntl.flock(store_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.db = sqlite3.connect(store / "jobs.sqlite3", check_same_thread=False)
            resources.callback(self.db.close)
            self.db.row_factory = sqlite3.Row
            self._initialize_db()
            self.pool = ThreadPoolExecutor(max_workers=1)
            resources.callback(self.pool.shutdown, wait=True)
            self.resources = resources.pop_all()

    def _initialize_db(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS blanks (id TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, submission_key TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
                status TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
                noise REAL NOT NULL, duration REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_running ON jobs(status) WHERE status='running';
            CREATE TABLE IF NOT EXISTS readings (
                job_id TEXT NOT NULL, ordinal INTEGER NOT NULL, record TEXT NOT NULL,
                PRIMARY KEY(job_id, ordinal)
            );
        """)
        with self.db:
            self.db.execute("UPDATE jobs SET status='interrupted', finished=? WHERE status='running'", (utc_now(),))

    def close(self):
        with self.lock, self.db:
            self.stopping = True
            self.db.execute("UPDATE jobs SET status='interrupted', finished=? WHERE status='running'", (utc_now(),))
            for event in self.active.values():
                event.set()
        self.resources.close()

    def _check_request(self, shape, request):
        validate(shape, request)
        validate_pins(request, self.capabilities)
        validate_settings(request["settings"], self.capabilities["profile"])
        if self.stopping:
            raise InstrumentError("service", "instrument is shutting down", 503)

    def _require_idle(self):
        if self.db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
            raise InstrumentError("instrument_id", "instrument has an active acquisition", 409)

    def _detector(self, expected):
        return max(0, min(ADC_MAX, round(self.rng.gauss(expected, self.noise))))

    def blank(self, request):
        with self.lock, self.db:
            self._check_request("blank_request", request)
            self._require_idle()
            settings = request["settings"]
            record = {**self.pin, "blank_id": uuid.uuid4().hex, "timestamp": utc_now(), "simulated": True,
                      "wavelength_nm": settings["wavelength_nm"], "path_length_mm": settings["path_length_mm"],
                      "dark_counts": self._detector(DARK_COUNTS), "blank_counts": self._detector(BLANK_COUNTS)}
            self.db.execute("INSERT INTO blanks VALUES (?,?)", (record["blank_id"], canonical(record)))
            return record

    def _reference(self, request):
        row = self.db.execute("SELECT record FROM blanks WHERE id=?", (request["blank_id"],)).fetchone()
        if row is None:
            raise InstrumentError("blank_id", "unknown reference")
        reference = json.loads(row["record"])
        for field, value in {**self.pin, **request["settings"]}.items():
            if field in reference and reference[field] != value:
                raise InstrumentError("blank_id", f"incompatible reference {field}")
        if not 0 <= reference["dark_counts"] < reference["blank_counts"] < ADC_MAX:
            raise InstrumentError("blank_id", "invalid reference detector counts")
        return reference

    def submit(self, request, key):
        validate_key(key)
        with self.lock:
            self._check_request("acquisition_request", request)
            settings = dict(request["settings"])
            for field in ("wavelength_nm", "path_length_mm", "replicates"):
                settings[field] = int(settings[field])
            request = {**request, "settings": settings}
            old = self.db.execute("SELECT id,request FROM jobs WHERE submission_key=?", (key,)).fetchone()
            if old:
                # Jobs from earlier versions may contain equivalent integral JSON floats.
                if json.loads(old["request"]) != request:
                    raise InstrumentError("Idempotency-Key", "already used for a different request", 409)
                return self.job(old["id"])
            self._require_idle()
            reference = self._reference(request)
            if any(sample not in self.samples for sample in request["sample_ids"]):
                raise InstrumentError("sample_ids", "unknown simulator sample")
            job_id = uuid.uuid4().hex
            started = self.monotonic()
            with self.db:
                self.db.execute("INSERT INTO jobs VALUES (?,?,?,'running',?,NULL,?,?)",
                                (job_id, key, canonical(request), utc_now(), self.noise, self.duration))
            stop = threading.Event()
            self.active[job_id] = stop
            self.pool.submit(self._run, job_id, request, reference, started, stop)
            return self.job(job_id)

    def _measure(self, job_id, reference, sample, replicate, elapsed):
        initial, rate = self.samples[sample]
        concentration = max(0, initial + rate * elapsed)
        attenuation = _COEFFICIENT[reference["wavelength_nm"]] * concentration
        expected = DARK_COUNTS + (BLANK_COUNTS - DARK_COUNTS) * 10 ** (-attenuation)
        record = {**reference, "timestamp": utc_now(), "job_id": job_id, "sample_id": sample, "replicate": replicate,
                  "elapsed_s": elapsed, "sample_counts": self._detector(expected), "unit": "counts",
                  "model_revision": _MODEL_REVISION, "findings": []}
        try:
            absorbance(record)
        except ValueError as error:
            record["findings"].append(str(error))
        return record

    def _run(self, job_id, request, reference, started, stop):
        try:
            ordinal = 0
            replicates = request["settings"]["replicates"]
            total = len(request["sample_ids"]) * replicates
            for sample in request["sample_ids"]:
                for replicate in range(1, replicates + 1):
                    self.wait(stop, self.duration)
                    with self.lock, self.db:
                        if stop.is_set():
                            return
                        record = self._measure(job_id, reference, sample, replicate, self.monotonic() - started)
                        ordinal += 1
                        self.db.execute("INSERT INTO readings VALUES (?,?,?)", (job_id, ordinal, canonical(record)))
                        if ordinal == total:
                            self.db.execute("UPDATE jobs SET status='completed', finished=? WHERE id=?", (utc_now(), job_id))
        except Exception:
            logging.exception("Interrupted virtual instrument job %s", job_id)
            with self.lock, self.db:
                self.db.execute("UPDATE jobs SET status='interrupted', finished=? WHERE id=? AND status='running'",
                                (utc_now(), job_id))
        finally:
            with self.lock:
                self.active.pop(job_id, None)

    def job(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise InstrumentError("job_id", "unknown acquisition", 404)
            count = self.db.execute("SELECT COUNT(*) FROM readings WHERE job_id=?", (job_id,)).fetchone()[0]
            return {**json.loads(row["request"]), "job_id": job_id, "status": row["status"], "started_at": row["started"],
                    "finished_at": row["finished"], "reading_count": count, "noise_sd_counts": row["noise"],
                    "duration_s": row["duration"], "simulated": True}

    def cancel(self, job_id):
        with self.lock, self.db:
            if self.job(job_id)["status"] == "running":
                self.db.execute("UPDATE jobs SET status='cancelled', finished=? WHERE id=?", (utc_now(), job_id))
                self.active[job_id].set()
            return self.job(job_id)

    def measurements(self, job_id):
        with self.lock:
            job = self.job(job_id)
            rows = self.db.execute("SELECT record FROM readings WHERE job_id=? ORDER BY ordinal", (job_id,))
            return {"schema_version": 1, "job_id": job_id, "complete": job["status"] == "completed",
                    "records": [json.loads(row["record"]) for row in rows]}
