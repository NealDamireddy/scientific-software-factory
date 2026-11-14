"""Trusted 550 nm simulator, frozen B12 calibration and independent release checks."""
from datetime import datetime, timezone
import hashlib
import json
import math
import random
import statistics

from .sandbox import execute

PROFILE = {
    "lab": "northfield",
    "project": "b12-assay",
    "instrument_profile": "osms-sim@1",
    "protocol": "b12-optical@1",
    "verification_profile": "optical-checks@1",
}
RECIPE = {"wavelength_nm": 550, "replicates": 3, "operation": "measure-absorbance"}
STANDARDS_MG_L = (3, 5, 10, 15, 20, 24)
ADC_MAX = 65535
DARK_COUNTS = 100
BLANK_COUNTS = 50000
DEFAULT_NOISE_COUNTS = 8
# Cyanocobalamin in aqueous solution, 1 cm path. Model the finite-bandwidth
# channel at its nominal centre, using 8700 M^-1 cm^-1 and 1355.37 g/mol.
MODEL_SLOPE = 8700 / (1000 * 1355.37)


def _finite_number(value):
    return type(value) in (int, float) and -math.inf < value < math.inf


def validate_recipe(recipe):
    if not isinstance(recipe, dict) or recipe.keys() != RECIPE.keys():
        raise ValueError("Recipe must declare operation, wavelength_nm and replicates")
    for key, supported in RECIPE.items():
        if recipe[key] != supported or type(recipe[key]) is not type(supported):
            raise ValueError(f"{PROFILE['instrument_profile']} supports only {key}={supported}")
    return dict(RECIPE)


def acquire(recipe, concentration, seed, *, sample_id="unknown", noise_counts=DEFAULT_NOISE_COUNTS):
    """Execute only registered optical commands. Sample labels and seeds stay private."""
    validate_recipe(recipe)
    if not _finite_number(concentration) or concentration < 0:
        raise ValueError("Simulated concentration must be finite and nonnegative")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("Missing sample identifier")
    if not _finite_number(noise_counts) or noise_counts < 0:
        raise ValueError("Invalid detector noise")
    settings = {
        **RECIPE, "path_length_mm": 10, "adc_max": ADC_MAX, "noise_sd_counts": noise_counts,
        "dark_offset_counts": DARK_COUNTS, "reference_counts": BLANK_COUNTS,
    }
    transmitted = DARK_COUNTS + (BLANK_COUNTS - DARK_COUNTS) * 10 ** (-MODEL_SLOPE * concentration)
    rng = random.Random(seed)

    def detector(expected):
        return max(0, min(ADC_MAX, round(rng.gauss(expected, noise_counts))))

    return [
        {
            "sample_id": sample_id, "replicate": replicate,
            "instrument_profile": PROFILE["instrument_profile"], "settings": settings.copy(),
            "timestamp": datetime.now(timezone.utc).isoformat(), "units": "counts",
            "source": "simulated instrument", "dark_counts": detector(DARK_COUNTS),
            "blank_counts": detector(BLANK_COUNTS), "sample_counts": detector(transmitted),
        }
        for replicate in range(1, recipe["replicates"] + 1)
    ]


def absorbance(record):
    dark, blank, sample = (record.get(key) for key in ("dark_counts", "blank_counts", "sample_counts"))
    if not all(_finite_number(count) and 0 <= count <= ADC_MAX for count in (dark, blank, sample)):
        raise ValueError("Invalid optical counts")
    if max(dark, blank, sample) >= ADC_MAX:
        raise ValueError("Saturated detector")
    if blank <= dark:
        raise ValueError("Invalid blank: reference must exceed the dark reading")
    if sample <= dark:
        raise ValueError("Invalid sample: no positive dark-corrected transmission")
    return -math.log10((sample - dark) / (blank - dark))


def fit_calibration(recipe, seed, *, noise_counts=DEFAULT_NOISE_COUNTS):
    """Fit on known standards only. The ID covers raw records as well as fitted values."""
    validate_recipe(recipe)
    rng = random.Random(seed)
    standards = []
    for concentration in STANDARDS_MG_L:
        raw = acquire(recipe, concentration, rng.getrandbits(64), sample_id=f"std-{concentration}",
                      noise_counts=noise_counts)
        mean = statistics.mean(absorbance(record) for record in raw)
        standards.append({"concentration_mg_l": concentration, "raw": raw, "mean_absorbance": mean})
    means = [standard["mean_absorbance"] for standard in standards]
    slope, intercept = statistics.linear_regression(STANDARDS_MG_L, means)
    if slope <= 0 or any(right <= left for left, right in zip(means, means[1:])):
        raise ValueError("Calibration standards must increase in absorbance with concentration")
    for standard in standards:
        predicted = slope * standard["concentration_mg_l"] + intercept
        standard["residual_absorbance"] = standard["mean_absorbance"] - predicted
    calibration = {
        "slope": slope, "intercept": intercept, "low": min(means), "high": max(means),
        "instrument_profile": PROFILE["instrument_profile"], "standards": standards,
    }
    canonical = json.dumps(calibration, sort_keys=True, separators=(",", ":"), allow_nan=False)
    calibration["id"] = hashlib.sha256(canonical.encode()).hexdigest()
    return calibration


def assess(raw, cal):
    if not isinstance(raw, list) or len(raw) != RECIPE["replicates"]:
        raise ValueError("Assessment requires three optical readings")
    if not all(_finite_number(cal.get(key)) for key in ("low", "high", "slope", "intercept")):
        raise ValueError("Invalid calibration values")
    if cal["low"] >= cal["high"] or cal["slope"] <= 0:
        raise ValueError("Invalid calibration bounds or slope")
    values = [absorbance(record) for record in raw]
    return {
        "absorbances": values, "in_range": all(cal["low"] <= a <= cal["high"] for a in values),
        "above_range": all(a > cal["high"] for a in values),
    }


def validate_preparation(sample_id, prep):
    """Check the actual, linked preparation before acquisition or correction."""
    if not isinstance(prep, dict):
        raise ValueError("preparation record required")
    identifiers = {"sample_id": sample_id, "parent_id": prep.get("parent_id"), "id": prep.get("id")}
    for field, identifier in identifiers.items():
        if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
            raise ValueError(f"Invalid {field}")
    if prep["parent_id"] == sample_id:
        raise ValueError("parent_id must differ from sample_id")
    if prep.get("unit") != "mL":
        raise ValueError("unit must be mL")
    for field in ("sample_ml", "final_ml"):
        if not _finite_number(prep.get(field)) or prep[field] <= 0:
            raise ValueError(f"{field} must be positive and finite")
    if prep["final_ml"] <= prep["sample_ml"]:
        raise ValueError("final_ml must exceed sample_ml")
    try:
        factor = prep["final_ml"] / prep["sample_ml"]
    except OverflowError as error:
        raise ValueError("Dilution factor must be finite") from error
    if not math.isfinite(factor):
        raise ValueError("Dilution factor must be finite")
    return factor


def _check_case(source, name, sample, expected):
    try:
        actual, _ = execute(source, json.dumps(sample, allow_nan=False).encode())
        passed = True
        for key, value in expected.items():
            if isinstance(value, (float, int)):
                observed = actual.get(key)
                if not _finite_number(observed) or not math.isclose(
                    value, observed, rel_tol=1e-7, abs_tol=1e-7
                ):
                    passed = False
            elif key not in actual or actual[key] != value:
                passed = False
        # Keep malformed worker output from contaminating JSON evidence.
        json.dumps(actual, allow_nan=False)
    except (ArithmeticError, OSError, TypeError, ValueError, RuntimeError) as error:
        actual = {"error": str(error)[:400]}
        passed = False
    return {"name": name, "pass": passed, "expected": expected, "actual": actual}


def verify_candidate(source, prepared=False):
    """Exercise unknowns spanning the range with a nonzero intercept in isolated processes."""
    cal = {"id": "ref-cal-v1", "slope": 0.01, "intercept": 0.02, "low": 0.05, "high": 0.26}
    fixtures = (
        ("direct-mean-and-intercept", (0.10, 0.11, 0.21), 12.0),
        ("direct-calibrated-boundaries", (0.05, 0.26, 0.20), 15.0),
        ("above-calibration", (0.27, 0.28, 0.29), None),
        ("below-calibration", (0.02, 0.03, 0.04), None),
        ("one-replicate-outside", (0.15, 0.17, 0.27), None),
    )
    checks = []
    for name, values, concentration in fixtures:
        sample = {"sample_id": name, "absorbances": values, "calibration": cal, "preparation": None}
        expected = {
            "sample_id": name, "calibration_id": cal["id"],
            "status": "review" if concentration is None else "ok", "concentration_mg_l": concentration,
        }
        checks.append(_check_case(source, name, sample, expected))
    if prepared:
        checks.extend(_verify_prepared(source, cal))
    return checks


def _verify_prepared(source, cal):
    twofold = {"id": "P2", "parent_id": "R2", "sample_ml": 1, "final_ml": 2, "unit": "mL"}
    fourfold = {"id": "P4", "parent_id": "R4", "sample_ml": 0.5, "final_ml": 2, "unit": "mL"}
    fixtures = [
        ("prepared-2x", "D2", (0.09, 0.10, 0.14), twofold, {
            "status": "ok", "concentration_mg_l": 18.0, "diluted_mg_l": 9.0,
            "factor": 2.0, "parent_id": "R2", "preparation_id": "P2",
        }),
        ("prepared-4x", "D4", (0.07, 0.08, 0.12), fourfold, {
            "status": "ok", "concentration_mg_l": 28.0, "diluted_mg_l": 7.0,
            "factor": 4.0, "parent_id": "R4", "preparation_id": "P4",
        }),
    ]
    review = {"status": "review", "concentration_mg_l": None}
    # A dilution does not guarantee that its new readings will be in range.
    fixtures.append(("prepared-one-outside", "D2", (0.21, 0.21, 0.27), twofold, review))
    for name, changes in (
        ("missing-parent", {"parent_id": None}), ("self-parent", {"parent_id": "D2"}),
        ("missing-preparation-id", {"id": ""}), ("invalid-unit", {"unit": "L"}),
        ("zero-sample", {"sample_ml": 0}), ("invalid-final-volume", {"final_ml": -1}),
        ("equal-volumes", {"final_ml": 1}), ("invalid-volume-type", {"sample_ml": True}),
    ):
        fixtures.append((f"prepared-{name}", "D2", (0.09, 0.10, 0.14), {**twofold, **changes}, review))

    checks = []
    for name, child, values, preparation, output in fixtures:
        sample = {"sample_id": child, "absorbances": values, "calibration": cal, "preparation": preparation}
        expected = {"sample_id": child, "calibration_id": cal["id"], **output}
        checks.append(_check_case(source, name, sample, expected))
    return checks
