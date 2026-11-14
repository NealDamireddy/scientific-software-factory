"""Shared v1 HTTP shapes and pin checks for the virtual instrument."""
import json
import re

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .context import ROOT, digest, read_json


class InstrumentError(ValueError):
    def __init__(self, field, reason, status=422):
        self.field = field
        self.reason = reason
        self.status = status
        super().__init__(f"{field}: {reason}")


SCHEMA = read_json(ROOT / "registry/uvvis-api-v1.schema.json")
SCHEMA_URI = "urn:evolve:uvvis-api-v1"
_REGISTRY = Registry().with_resource(SCHEMA_URI, Resource.from_contents(SCHEMA))
_VALIDATORS = {
    name: Draft202012Validator({"$ref": f"{SCHEMA_URI}#/$defs/{name}"}, registry=_REGISTRY)
    for name in SCHEMA["$defs"]
}


def validate_key(key):
    if not isinstance(key, str) or re.fullmatch(r"[!-~]{1,200}", key) is None:
        raise InstrumentError("Idempotency-Key", "supply 1–200 printable ASCII characters without spaces")


def validate_job_id(job_id):
    if not isinstance(job_id, str) or re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
        raise InstrumentError("job_id", "expected a 32-character lowercase hexadecimal job ID")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def profile_sha256(profile):
    return digest(canonical(profile).encode("utf-8"))


def validate(shape, payload):
    error = next(_VALIDATORS[shape].iter_errors(payload), None)
    if error:
        field = ".".join(str(part) for part in error.absolute_path) or shape
        raise InstrumentError(field, error.message)


def load_profile():
    registry = ROOT / "registry"
    profile = read_json(registry / "virtual-uvvis.profile.json")
    Draft202012Validator(read_json(registry / "instrument-profile.schema.json")).validate(profile)
    if profile["profile_id"] != "virtual-uvvis@1" or profile["simulated"] is not True:
        raise ValueError("Expected the virtual-uvvis@1 simulated profile")
    return profile


def validate_pins(request, capabilities):
    for name in ("instrument_id", "profile_id", "profile_sha256"):
        if request[name] != capabilities[name]:
            raise InstrumentError(name, "does not match live instrument capabilities", 409)


def validate_settings(settings, profile):
    validate("settings", settings)
    for field, supported in (("operation", "operations"), ("wavelength_nm", "wavelengths_nm"),
                             ("path_length_mm", "path_lengths_mm")):
        if settings[field] not in profile[supported]:
            raise InstrumentError(field, "unsupported by this instrument profile")
    limits = profile["replicate_limits"]
    if type(settings["replicates"]) is not int or not limits["min"] <= settings["replicates"] <= limits["max"]:
        raise InstrumentError("replicates", "outside the integer replicate limits")
