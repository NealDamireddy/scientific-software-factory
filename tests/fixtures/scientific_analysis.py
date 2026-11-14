"""Standalone, offline candidate used to exercise both scientific release contracts."""
from datetime import datetime, timedelta
import json
import math
import statistics
import sys


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def absorbances(records, sample_id, calibration):
    if not records:
        raise ValueError("Missing replicate readings")
    pins = ("instrument_id", "profile_id", "profile_sha256", "blank_id", "wavelength_nm", "path_length_mm")
    values = []
    seen = set()
    for reading in records:
        if not isinstance(reading, dict):
            raise ValueError("Expected a raw measurement record")
        if reading["sample_id"] != sample_id or not sample_id:
            raise ValueError("Sample identity mismatch")
        if any(reading[key] != calibration[key] for key in pins):
            raise ValueError("Measurement settings or blank differ from calibration")
        if reading["unit"] != "counts":
            raise ValueError("Measurement requires detector counts")
        if reading["simulated"] is not True or reading["findings"] != []:
            raise ValueError("Unverified measurement provenance or acquisition finding")
        timestamp = reading["timestamp"]
        if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset() != timedelta(0):
            raise ValueError("Measurement requires a UTC timestamp")
        if finite(reading["elapsed_s"], "elapsed time") < 0:
            raise ValueError("Negative elapsed time")
        replicate = reading["replicate"]
        if type(replicate) is not int or replicate < 1 or replicate in seen:
            raise ValueError("Invalid or repeated replicate")
        seen.add(replicate)
        dark, blank, sample = (reading[key] for key in ("dark_counts", "blank_counts", "sample_counts"))
        if any(type(count) is not int or not 0 <= count < 65535 for count in (dark, blank, sample)):
            raise ValueError("Invalid or saturated detector counts")
        if min(blank, sample) <= dark:
            raise ValueError("Dark-corrected blank and sample must be positive")
        values.append(-math.log10((sample - dark) / (blank - dark)))
    return values


def calibration_parameters(data):
    calibration = data["calibration"]
    if calibration["unit"] != "mg/L" or not calibration["id"]:
        raise ValueError("Calibration requires an identity and mg/L units")
    if data["experiment_type"] == "time_course":
        slope, intercept, low, high = (finite(calibration[key], key) for key in ("slope", "intercept", "low", "high"))
    elif data["experiment_type"] == "concentration":
        concentrations = []
        means = []
        for standard in data["standards"]:
            concentration = finite(standard["concentration"], "standard concentration")
            if standard["unit"] != "mg/L" or concentration <= 0:
                raise ValueError("Standard requires a positive concentration in mg/L")
            readings = standard["records"]
            means.append(statistics.mean(absorbances(readings, readings[0]["sample_id"], calibration)))
            concentrations.append(concentration)
        if len(set(concentrations)) < 3:
            raise ValueError("At least three distinct standards are required")
        slope, intercept = statistics.linear_regression(concentrations, means)
        low, high = min(means), max(means)
    else:
        raise ValueError("Unsupported experiment")
    if not all(map(math.isfinite, (slope, intercept, low, high))) or slope <= 0 or high <= low:
        raise ValueError("Invalid calibration slope or range")
    return slope, intercept, low, high


def analyze(data):
    calibration = data["calibration"]
    failures = (ValueError, KeyError, TypeError, IndexError, OverflowError)
    try:
        slope, intercept, low, high = calibration_parameters(data)
        calibration_error = None
    except failures as error:
        calibration_error = f"Invalid calibration: {error}"

    results = []
    for group in data["groups"]:
        row = {"sample_id": group["sample_id"], "concentration_mg_l": None, "replicate_sd_mg_l": None,
               "review_reason": calibration_error}
        records = group["records"]
        if data["experiment_type"] == "time_course":
            first = records[0] if isinstance(records, list) and records else None
            row["timestamp"] = first.get("timestamp") if isinstance(first, dict) else None
        if calibration_error is None:
            try:
                values = absorbances(records, group["sample_id"], calibration)
                if any(value < low or value > high for value in values):
                    raise ValueError("Replicate outside calibration range")
                concentration = finite((statistics.mean(values) - intercept) / slope, "estimate")
                spread = finite(statistics.stdev(values) / slope, "sample SD") if len(values) > 1 else None
                row.update(concentration_mg_l=concentration, replicate_sd_mg_l=spread)
            except failures as error:
                row["review_reason"] = f"Review measurement: {error}"
        results.append(row)
    return {"calibration_id": calibration["id"], "results": results}


if __name__ == "__main__":
    print(json.dumps(analyze(json.load(sys.stdin)), allow_nan=False))
