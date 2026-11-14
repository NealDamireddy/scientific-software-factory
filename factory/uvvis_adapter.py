"""Trusted HTTP client for v1 simulated acquisitions."""
import http.client
import json
import math
from urllib.parse import urlsplit

from .uvvis_contract import (
    InstrumentError, canonical, profile_sha256, validate, validate_job_id, validate_key, validate_pins, validate_settings,
)


class InstrumentUnavailable(ConnectionError):
    """Live service unavailable. A keyed submission can be reconciled by retrying."""


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
                result = json.loads(response.read(8 * 1024 * 1024 + 1))
                if response.status >= 300:
                    raise InstrumentError(result["field"], result["reason"], response.status)
                # A malformed success response can follow an accepted POST. It is
                # not an authoritative rejection and must not free a scheduling lease.
                try:
                    validate(shape, result)
                except InstrumentError as error:
                    raise InstrumentUnavailable("invalid simulator response") from error
                return result
            except InstrumentError:
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
        return self._request("POST", "/v1/blanks", "blank", payload=request)

    def submit(self, settings, sample_ids, blank_id, key):
        validate_key(key)
        request = self._checked("acquisition_request", settings, sample_ids=sample_ids, blank_id=blank_id)
        return self._request("POST", "/v1/acquisitions", "job", payload=request, key=key, retry=True)

    def poll(self, job_id):
        validate_job_id(job_id)
        return self._request("GET", f"/v1/acquisitions/{job_id}", "job", retry=True)

    def cancel(self, job_id):
        validate_job_id(job_id)
        return self._request("POST", f"/v1/acquisitions/{job_id}/cancel", "job", retry=True)

    def measurements(self, job_id):
        validate_job_id(job_id)
        return self._request("GET", f"/v1/acquisitions/{job_id}/measurements", "measurements", retry=True)
