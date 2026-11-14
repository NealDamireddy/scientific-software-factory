"""Independent public-count challenges for the v1 scientific release contracts.

Candidate stdin contains a calibration, standard groups (concentration only) and
sample groups. Each group carries raw v1 measurement records. A time-course group
is one acquisition timepoint, identified by the timestamp of its first replicate.
Output preserves group order and reports sample SD in concentration units.
"""
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone

TOLERANCE = 1e-7
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


def cases(experiment_type, compiled_recipe):
    """Yield (check name, category, public input, independent reference output)."""
    if experiment_type not in ("concentration", "time_course"):
        raise ValueError("Unsupported scientific experiment type")
    data, expected = _fixture(experiment_type, compiled_recipe)
    yield "nonzero intercept, sample SD and identities", "numerical", data, expected
    yield ("alternate calibration, samples and acquisition times", "numerical",
           *_fixture(experiment_type, compiled_recipe, alternate=True))

    # Only one replicate is invalid. All other sample/timepoint estimates must survive.
    profile_sha = data["calibration"]["profile_sha256"]
    different_sha = ("1" if profile_sha[0] == "0" else "0") + profile_sha[1:]
    for name, category, field, value in (
        ("measurement units", "input-validation", "unit", "AU"),
        ("nonfinite detector value", "input-validation", "sample_counts", float("nan")),
        ("dark-corrected transmission", "input-validation", "sample_counts", 128),
        ("detector findings", "input-validation", "findings", ["saturated detector"]),
        ("above calibration range", "numerical", "sample_counts", 128 + (32768 >> 7)),
        ("below calibration range", "numerical", "sample_counts", 128 + (32768 >> 1)),
        ("wavelength compatibility", "settings", "wavelength_nm", compiled_recipe["settings"]["wavelength_nm"] + 1),
        ("path length compatibility", "settings", "path_length_mm", compiled_recipe["settings"]["path_length_mm"] + 1),
        ("blank identity", "provenance", "blank_id", "unreferenced-blank"),
        ("instrument identity", "provenance", "instrument_id", data["calibration"]["instrument_id"] + "-other"),
        ("profile revision", "provenance", "profile_id", data["calibration"]["profile_id"] + "-other"),
        ("profile digest", "provenance", "profile_sha256", different_sha),
        ("sample identity", "provenance", "sample_id", "misassigned-vial"),
        ("simulated provenance", "provenance", "simulated", False),
    ):
        challenge, target = deepcopy(data), deepcopy(expected)
        challenge["groups"][0]["records"][-1][field] = value
        _withhold(target["results"][0])
        yield name, category, challenge, target

    reviewed = deepcopy(expected)
    for row in reviewed["results"]:
        _withhold(row)

    invalid_units = deepcopy(data)
    invalid_units["calibration"]["unit"] = "mmol/L"
    yield "calibration concentration units", "input-validation", invalid_units, reviewed

    if experiment_type == "time_course":
        for name, field, value in (("positive frozen slope", "slope", 0),
                                   ("ordered calibration range", "high", 0)):
            challenge = deepcopy(data)
            challenge["calibration"][field] = value
            yield name, "input-validation", challenge, reviewed
    else:
        for name, field, value in (
            ("distinct known standards", "concentration", data["standards"][1]["concentration"]),
            ("positive known standards", "concentration", 0),
            ("standard concentration units", "unit", "mmol/L"),
        ):
            challenge = deepcopy(data)
            challenge["standards"][0][field] = value
            yield name, "input-validation", challenge, reviewed
        reversed_fit = deepcopy(data)
        for standard, source in zip(reversed_fit["standards"], reversed(data["standards"])):
            standard["concentration"] = source["concentration"]
        yield "positive fitted slope", "numerical", reversed_fit, reviewed

        broken_reference = deepcopy(data)
        broken_reference["standards"][1]["records"][0]["blank_id"] = "unreferenced-blank"
        yield "standard blank identity", "provenance", broken_reference, reviewed


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
