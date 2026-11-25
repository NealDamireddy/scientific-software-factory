"""Trusted HTTP client for v1 simulated acquisitions."""
import http.client
import json
import math
from urllib.parse import urlsplit

from factory.instruments.uvvis_contract import (
    InstrumentError, canonical, pin_sha256, profile_sha256, validate, validate_job_id, validate_key,
    validate_pins, validate_settings,
)


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class InstrumentUnavailable(ConnectionError):
    """Live service unavailable. A keyed submission can be reconciled by retrying."""


def _match_response(response, expected):
    """A conflicting success is ambiguous even when its shape is valid."""
    for field, value in expected.items():
        if response[field] != value:
            raise InstrumentUnavailable(f"simulator response {field} does not match the request")


def _immutable_job_fields(job):
    return {field: value for field, value in job.items() if field not in ("status", "finished_at", "reading_count")}


class VirtualInstrumentAdapter:
    def __init__(self, base_url, instrument_id, profile_id, profile_digest, *, timeout=2):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
                or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("A loopback HTTP service origin is required")
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("timeout must be in (0, 60] seconds")
        self.host = url.hostname
        self.port = url.port or 80
        self.timeout = timeout
        self.pin = {"schema_version": 1, "instrument_id": instrument_id,
                    "profile_id": profile_id, "profile_sha256": profile_digest}
        validate("pin", self.pin)

    def _request(self, method, path, shape, *, payload=None, key=None, retry=False):
        body = canonical(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if key is not None:
            headers["Idempotency-Key"] = key
        for attempt in range(2 if retry else 1):
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            try:
                conn.request(method, path, body, headers)
                response = conn.getresponse()
                if response.status >= 500:
                    raise InstrumentUnavailable(f"instrument returned HTTP {response.status}")
                expected_length = response.length
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if (len(raw) > _MAX_RESPONSE_BYTES or
                        (expected_length is not None and len(raw) != expected_length)):
                    raise InstrumentUnavailable("invalid simulator response length")
                result = json.loads(raw)
                if response.status >= 300:
                    raise InstrumentError(result["field"], result["reason"], response.status)
                # A malformed success response can follow an accepted POST. It is
                # not an authoritative rejection and must not free a scheduling lease.
                try:
                    validate(shape, result)
                except InstrumentError as error:
                    raise InstrumentUnavailable("invalid simulator response") from error
                return result
            except InstrumentError as error:
                if attempt and key is not None:
                    # A rejection on retry says nothing about the first POST.
                    raise InstrumentUnavailable("unable to reconcile the keyed submission") from error
                raise
            except (OSError, http.client.HTTPException) as error:
                if not retry or attempt == 1:
                    raise InstrumentUnavailable("local simulator unavailable") from error
            except (ValueError, KeyError, TypeError) as error:
                raise InstrumentUnavailable("invalid simulator response") from error
            finally:
                conn.close()

    def capabilities(self):
        result = self._request("GET", "/v1/capabilities", "capabilities", retry=True)
        validate_pins(self.pin, result)
        profile = result["profile"]
        if (profile_sha256(profile) != self.pin["profile_sha256"] or profile.get("profile_id") != self.pin["profile_id"]
                or profile.get("schema_version") != 1 or profile.get("simulated") is not True):
            raise InstrumentError("profile", "live projection does not match the pinned simulated profile", 409)
        return result

    def _checked(self, shape, settings, **fields):
        request = {**self.pin, "settings": settings, **fields}
        validate(shape, request)
        validate_settings(settings, self.capabilities()["profile"])
        return request

    def blank(self, settings):
        request = self._checked("blank_request", settings)
        blank = self._request("POST", "/v1/blanks", "blank", payload=request)
        _match_response(blank, self.pin)
        return blank

    def submit(self, settings, sample_ids, blank_id, key):
        validate_key(key)
        request = self._checked("acquisition_request", settings, sample_ids=sample_ids, blank_id=blank_id)
        job = self._request("POST", "/v1/acquisitions", "job", payload=request, key=key, retry=True)
        _match_response(job, request)
        try:
            validate_job_id(job["job_id"])
        except InstrumentError as error:
            raise InstrumentUnavailable("invalid simulator response job_id") from error
        return job

    def _job_path(self, job_id, suffix=""):
        return f"/v1/acquisitions/{job_id}{suffix}?pin_sha256={pin_sha256(self.pin)}"

    def poll(self, job_id, *, expected_request=None):
        validate_job_id(job_id)
        profile = self.capabilities()["profile"]
        job = self._request("GET", self._job_path(job_id), "job", retry=True)
        _match_response(job, {**self.pin, "job_id": job_id})
        try:
            validate_settings(job["settings"], profile)
            if expected_request is not None:
                validate("acquisition_request", expected_request)
                _match_response(job, expected_request)
        except InstrumentError as error:
            raise InstrumentUnavailable(f"cannot validate simulator job: {error}") from error
        return job

    def cancel(self, job_id, *, expected_request=None):
        previous = self.poll(job_id, expected_request=expected_request)
        job = self._request("POST", self._job_path(job_id, "/cancel"), "job", payload=self.pin, retry=True)
        _match_response(job, _immutable_job_fields(previous))
        return job

    def measurements(self, job_id, *, expected_request=None):
        # A partial v1 measurement envelope can be empty and contains no pins.
        job = self.poll(job_id, expected_request=expected_request)
        result = self._request("GET", self._job_path(job_id, "/measurements"), "measurements", retry=True)
        _match_response(result, {"job_id": job_id})
        if result["complete"] and job["status"] == "running":
            # A job can finish between the two reads. Confirm on the guarded job route.
            confirmed = self.poll(job_id, expected_request=expected_request)
            _match_response(confirmed, _immutable_job_fields(job))
            job = confirmed
        if result["complete"] != (job["status"] == "completed"):
            raise InstrumentUnavailable("measurement completeness contradicts the simulator job status")
        expected = {**self.pin, "job_id": job_id, "blank_id": job["blank_id"],
                    "wavelength_nm": job["settings"]["wavelength_nm"],
                    "path_length_mm": job["settings"]["path_length_mm"]}
        samples = set(job["sample_ids"])
        replicates = job["settings"]["replicates"]
        seen = set()
        for record in result["records"]:
            _match_response(record, expected)
            sample, replicate = record["sample_id"], record["replicate"]
            if sample not in samples:
                raise InstrumentUnavailable("simulator response sample_id does not belong to the job")
            if replicate > replicates or (sample, replicate) in seen:
                raise InstrumentUnavailable("simulator response has an unexpected replicate")
            seen.add((sample, replicate))
        if result["complete"] and len(seen) != len(samples) * replicates:
            raise InstrumentUnavailable("complete simulator response is missing replicates")
        return result
