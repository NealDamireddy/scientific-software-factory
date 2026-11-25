"""Independent public-count challenges for the v1 scientific release contracts.

Candidate stdin contains a calibration, standard groups (concentration only) and
sample groups. Each group carries raw v1 measurement records. A time-course group
is one acquisition timepoint, identified by the timestamp of its first replicate.
Output preserves group order and reports sample SD in concentration units.
"""
import math
from datetime import datetime, timedelta, timezone
from functools import partial

TOLERANCE = 1e-7
VERIFIER = "scientific-release@6"
_LOG_TWO = math.log10(2)
_REVIEW = object()
_EPOCH = datetime(2026, 2, 3, 14, 5, tzinfo=timezone.utc)


def _records(calibration, sample_id, levels, start):
    """Level n is exactly 2**-n transmission after subtracting the dark count."""
    pins = {key: calibration[key] for key in (
        "instrument_id", "profile_id", "profile_sha256", "wavelength_nm",
        "path_length_mm", "blank_id",
    )}
    rows = []
    for replicate, level in enumerate(levels, 1):
        elapsed = start + (replicate - 1) / 4
        rows.append({
            **pins, "schema_version": 1, "sample_id": sample_id, "replicate": replicate,
            "timestamp": (_EPOCH + timedelta(seconds=elapsed)).isoformat(),
            "elapsed_s": elapsed, "job_id": f"{int(start * 1000):032x}",
            "dark_counts": 128, "blank_counts": 32896, "sample_counts": 128 + (32768 >> level),
            "unit": "counts", "model_revision": "optical-reference@1", "simulated": True,
            "findings": [],
        })
    return rows


def _fixture(kind, recipe, alternate=False):
    calibration = {
        "id": "calibrant-Q7" if alternate else "calibrant-F2", "unit": "mg/L",
        **{key: recipe[key] for key in ("instrument_id", "profile_id", "profile_sha256")},
        **{key: recipe["settings"][key] for key in ("wavelength_nm", "path_length_mm")},
        "blank_id": "reference-Q7" if alternate else "reference-F2",
    }
    standards = []
    if kind == "concentration":
        # In units of log10(2), standard means are 2, 3, 6 at x = 2, 4, 8.
        # Solving the normal equations gives slope 19/28 and intercept 1/2.
        # Shifting each standard down one concentration unit changes the intercept.
        slope = 19 / 28
        intercept = .5 + (slope if alternate else 0)
        for index, (known, center) in enumerate(((2, 2), (4, 3), (8, 6)), 1):
            sample = f"standard-{index}"
            records = _records(calibration, sample, (center - 1, center, center + 1), index)
            standards.append({"concentration": known - int(alternate), "unit": "mg/L",
                              "records": records})
    else:
        slope, intercept = (.31, .91) if alternate else (.4, .7)
        calibration.update(slope=slope * _LOG_TWO, intercept=intercept * _LOG_TWO,
                           low=2 * _LOG_TWO, high=6 * _LOG_TWO)

    name = "violet-36" if alternate else "copper-14"
    other = "coral-57" if alternate else "ochre-83"
    first = (4, 5) if alternate else (3, 4, 5)
    # Sample deviations for (4,5) and (3,4,5) are sqrt(1/2) and 1.
    point_data = [
        (name, first, 4.5 if alternate else 4, math.sqrt(.5) if alternate else 1, 7.375),
        (name if kind == "time_course" else other, (3,), 3, None, 19.625),
        (other, (5, 3), 4, math.sqrt(2), 42.125),
    ]
    if alternate:
        # Both endpoints are valid, even when they occur in the same replicate group.
        point_data.append((other, (2, 6), 4, math.sqrt(8), 65.25))
    groups = []
    results = []
    for sample, levels, mean, spread, start in point_data:
        records = _records(calibration, sample, levels, start + (2.5 if alternate else 0))
        groups.append({"sample_id": sample, "records": records})
        row = {"sample_id": sample, "concentration_mg_l": (mean - intercept) / slope,
               "replicate_sd_mg_l": None if spread is None else spread / slope, "review_reason": None}
        if kind == "time_course":
            row["timestamp"] = records[0]["timestamp"]
        results.append(row)
    return (
        {"experiment_type": kind, "calibration": calibration, "standards": standards, "groups": groups},
        {"calibration_id": calibration["id"], "results": results},
    )


def _withhold(row):
    row.update(concentration_mg_l=None, replicate_sd_mg_l=None, review_reason=_REVIEW)


# Mutations below damage one independent public fixture at a time. They are
# evaluated only when trusted inputs are available to construct a challenge.
def _invalid_reading(kind, field, replacement, recipe):
    payload, expected = _fixture(kind, recipe)
    record = payload["groups"][0]["records"][-1]
    if replacement is None:
        del record[field]
    elif callable(replacement):
        record[field] = replacement(record[field])
    else:
        record[field] = replacement
    _withhold(expected["results"][0])
    return payload, expected


def _shift_counts(kind, offset, recipe):
    payload, expected = _fixture(kind, recipe)
    record = payload["groups"][0]["records"][-1]
    # A common detector offset cancels from both dark-corrected differences.
    # Only validating raw counts can reject these optically identical readings.
    for field in ("dark_counts", "blank_counts", "sample_counts"):
        record[field] += offset
    _withhold(expected["results"][0])
    return payload, expected


def _negative_corrected_signals(kind, recipe, *, single_replicate):
    payload, expected = _fixture(kind, recipe)
    records = payload["groups"][0]["records"]
    for record in (records[-1:] if single_replicate else records):
        # Reverse both corrected signals while retaining their in-range ratio.
        # All three raw counts stay within the detector's unsigned range.
        dark = record["dark_counts"]
        record["blank_counts"] = 40000 - (record["blank_counts"] - dark)
        record["sample_counts"] = 40000 - (record["sample_counts"] - dark)
        record["dark_counts"] = 40000
    _withhold(expected["results"][0])
    return payload, expected


def _invalid_calibration(kind, change, recipe):
    payload, expected = _fixture(kind, recipe)
    change(payload)
    for row in expected["results"]:
        _withhold(row)
    return payload, expected


def _frozen_value(field, value, recipe):
    return _invalid_calibration("time_course", lambda p: p["calibration"].update({field: value}), recipe)


def _conflicting_standards(recipe):
    payload, expected = _fixture("time_course", recipe)
    # Compatible pins, but the standard-derived slope is 19/28 rather than 0.4
    # in units of log10(2). The referenced frozen calibration remains authoritative.
    concentration, _ = _fixture("concentration", recipe)
    payload["standards"] = concentration["standards"]
    return payload, expected


def _remove_reference(payload):
    payload["calibration"]["blank_id"] = None
    for group in payload["groups"] + payload["standards"]:
        for record in group["records"]:
            record["blank_id"] = None


def _reverse_standard_concentrations(payload):
    standards = payload["standards"]
    concentrations = [standard["concentration"] for standard in reversed(standards)]
    for standard, concentration in zip(standards, concentrations):
        standard["concentration"] = concentration


def case_plan(kind):
    """Yield check names/categories and lazy builders, without needing any handoff data."""
    if kind not in ("concentration", "time_course"):
        raise ValueError("Unsupported scientific experiment type")
    yield "nonzero intercept, sample SD and identities", "numerical", partial(_fixture, kind)
    yield ("alternate calibration, samples and acquisition times", "numerical",
           partial(_fixture, kind, alternate=True))

    # A single bad replicate withholds only its group. Deliberately malformed
    # detector values still imply in-range absorbance if the raw-count guard is absent.
    for name, category, field, value in (
        ("measurement units", "input-validation", "unit", "AU"),
        ("nonfinite detector value", "input-validation", "sample_counts", float("nan")),
        ("dark-corrected transmission", "input-validation", "sample_counts", 128),
        ("detector findings", "input-validation", "findings", ["saturated detector"]),
        ("nonfinite elapsed time", "input-validation", "elapsed_s", float("nan")),
        ("positive infinite elapsed time", "input-validation", "elapsed_s", math.inf),
        ("negative infinite elapsed time", "input-validation", "elapsed_s", -math.inf),
        ("negative elapsed time", "input-validation", "elapsed_s", -.25),
        ("missing measurement timestamp", "input-validation", "timestamp", None),
        ("malformed measurement timestamp", "input-validation", "timestamp", "not-a-timestamp"),
        ("non-UTC measurement timestamp", "input-validation", "timestamp", "2026-02-03T10:05:07-04:00"),
        ("repeated replicate identity", "input-validation", "replicate", 1),
        ("nonpositive replicate identity", "input-validation", "replicate", 0),
        ("fractional replicate identity", "input-validation", "replicate", 2.5),
        ("above calibration range", "numerical", "sample_counts", 128 + (32768 >> 7)),
        ("below calibration range", "numerical", "sample_counts", 128 + (32768 >> 1)),
        ("wavelength compatibility", "settings", "wavelength_nm", lambda n: n + 1),
        ("path length compatibility", "settings", "path_length_mm", lambda n: n + 1),
        ("unsupported measurement schema", "provenance", "schema_version", 2),
        ("invalid acquisition identity", "provenance", "job_id", "invalid"),
        ("mixed acquisition replicates", "provenance", "job_id", "f" * 32),
        ("mixed model revisions", "provenance", "model_revision", "other-optical@2"),
        ("blank identity", "provenance", "blank_id", "unreferenced-blank"),
        ("instrument identity", "provenance", "instrument_id", lambda s: s + "-other"),
        ("profile revision", "provenance", "profile_id", lambda s: s + "-other"),
        ("profile digest", "provenance", "profile_sha256", lambda s: ("1" if s[0] == "0" else "0") + s[1:]),
        ("sample identity", "provenance", "sample_id", "misassigned-vial"),
        ("simulated provenance", "provenance", "simulated", False),
        ("missing measurement schema_version", "provenance", "schema_version", None),
        ("missing measurement model_revision", "provenance", "model_revision", None),
    ):
        yield name, category, partial(_invalid_reading, kind, field, value)

    for name, offset in (("negative detector counts", -129), ("fractional detector counts", .5),
                         ("saturated detector counts", 65535 - 32896)):
        yield name, "input-validation", partial(_shift_counts, kind, offset)

    yield ("negative dark-corrected signals", "input-validation",
           partial(_negative_corrected_signals, kind, single_replicate=False))
    yield ("negative dark-corrected signals in one replicate", "input-validation",
           partial(_negative_corrected_signals, kind, single_replicate=True))

    yield "required blank reference", "provenance", partial(_invalid_calibration, kind, _remove_reference)
    calibration_changes = [
        ("calibration concentration units", "input-validation", lambda p: p["calibration"].update(unit="mmol/L")),
    ]
    if kind == "time_course":
        for field in ("slope", "intercept", "low", "high"):
            for label, value in (("NaN", math.nan), ("positive infinite", math.inf),
                                 ("negative infinite", -math.inf)):
                yield f"{label} frozen {field}", "input-validation", partial(_frozen_value, field, value)
        yield "supplied standards cannot replace frozen fit", "numerical", _conflicting_standards
        calibration_changes.extend([
            ("positive frozen slope", "input-validation", lambda p: p["calibration"].update(slope=0)),
            ("negative frozen slope", "input-validation", lambda p: p["calibration"].update(slope=-1)),
            ("ordered calibration range", "input-validation", lambda p: p["calibration"].update(high=0)),
            # The singleton timepoint is exactly at this absorbance. Merely checking each
            # replicate against an inclusive range cannot reject a zero-width fit.
            ("equal calibration bounds", "input-validation",
             lambda p: p["calibration"].update(low=-math.log10(.125), high=-math.log10(.125))),
        ])
    else:
        calibration_changes.extend([
            ("distinct known standards", "input-validation",
             lambda p: p["standards"][0].update(concentration=p["standards"][1]["concentration"])),
            ("positive known standards", "input-validation", lambda p: p["standards"][0].update(concentration=0)),
            ("standard concentration units", "input-validation", lambda p: p["standards"][0].update(unit="mmol/L")),
            ("positive fitted slope", "numerical", _reverse_standard_concentrations),
            ("standard blank identity", "provenance",
             lambda p: p["standards"][1]["records"][0].update(blank_id="unreferenced-blank")),
            ("mixed acquisition in standard", "provenance",
             lambda p: p["standards"][1]["records"][0].update(job_id="f" * 32)),
        ])
    for name, category, change in calibration_changes:
        yield name, category, partial(_invalid_calibration, kind, change)


def cases(experiment_type, compiled_recipe):
    """Yield (check name, category, public input, independent reference output)."""
    for name, category, build in case_plan(experiment_type):
        yield name, category, *build(compiled_recipe)


def compare(actual, expected, path="output"):
    """Require the complete result schema and report the first differing field."""
    if expected is _REVIEW:
        if not isinstance(actual, str) or not actual.strip():
            raise ValueError(f"{path} requires a review reason")
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise ValueError(f"{path} must contain exactly {sorted(expected)}")
        for key, value in expected.items():
            compare(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"{path} expects {len(expected)} rows")
        for index, (item, value) in enumerate(zip(actual, expected)):
            compare(item, value, f"{path}[{index}]")
    elif type(expected) in (int, float):
        try:
            matches = type(actual) in (int, float) and math.isclose(
                actual, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)
        except OverflowError:
            matches = False
        if not matches:
            raise ValueError(f"{path} outside contract tolerance")
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"{path} differs from reference")
