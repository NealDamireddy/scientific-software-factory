"""Host-side validation of known UV–Vis standards before publishing a reusable fit."""
from datetime import datetime, timedelta
import math
import statistics

from .context import digest
from .optics import absorbance
from .scientific_analysis import finite
from .uvvis_contract import canonical, validate, validate_job_id


def fit_standards(inputs):
    """Return the immutable calibration payload, or None for unusable standards.

    The caller groups a complete job against its approved sample IDs and replicate
    count. Unknown-vial results have no bearing on the quality of the standards.
    """
    cal, standards = inputs["calibration"], inputs["standards"]
    if cal["unit"] != "mg/L":
        return None
    levels, means = [], []
    try:
        for standard in standards:
            level = standard["concentration"]
            if not finite(level) or level <= 0 or standard["unit"] != cal["unit"]:
                return None
            values = []
            acquisition_model = None
            for reading in standard["records"]:
                validate("measurement_record", reading)
                validate_job_id(reading["job_id"])
                # The wire schema permits integral floats for optical settings.
                # For counts, schema, and replicate the analysis requires actual integers.
                if any(type(reading[k]) is not int for k in
                       ("schema_version", "replicate", "dark_counts", "blank_counts", "sample_counts")):
                    return None
                if (reading["findings"] or not finite(reading["elapsed_s"])
                        or datetime.fromisoformat(reading["timestamp"]).utcoffset() != timedelta(0)
                        or not reading["model_revision"].strip()):
                    return None
                identity = (reading["job_id"], reading["model_revision"])
                if acquisition_model is not None and identity != acquisition_model:
                    return None
                acquisition_model = identity
                values.append(absorbance(reading))
            levels.append(level)
            means.append(statistics.mean(values))
        if len(set(levels)) < 3:
            return None
        slope, intercept = statistics.linear_regression(levels, means)
        low, high = min(means), max(means)
        if not all(map(math.isfinite, (slope, intercept, low, high))) or slope <= 0 or high <= low:
            return None
    except (ArithmeticError, ValueError, KeyError, TypeError):
        return None
    return dict(cal, slope=slope, intercept=intercept, low=low, high=high,
                standards_sha256=digest(canonical(standards).encode()))
