"""Check retained B12 measurement evidence using only the public detector records."""
from contextlib import contextmanager
from datetime import datetime
import math
from statistics import linear_regression, mean

from .followup import _payload
from .optics import ADC_MAX, BLANK_COUNTS, DARK_COUNTS, PROFILE, RECIPE, STANDARDS_MG_L, validate_preparation


@contextmanager
def record(path):
    """Annotate failures with the location in the downloaded evidence package."""
    try:
        yield
    except KeyError as error:
        raise ValueError(f"{path}.{error.args[0]} is missing") from error
    except (ValueError, TypeError, AttributeError, ArithmeticError) as error:
        raise ValueError(f"{path}: {error}") from error


def require(condition, field):
    if not condition:
        raise ValueError(field)


def text_field(data, key):
    value = data[key]
    require(isinstance(value, str) and value.strip(), f"{key} must contain text")
    return value


def number_matches(actual, expected):
    return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-7, abs_tol=1e-7)


def timestamp(data, key):
    with record(key):
        value = datetime.fromisoformat(text_field(data, key))
        require(value.utcoffset() is not None, "timestamp requires a timezone")


def _reading_evidence(raw, cal, sample, prep, recipe):
    require(isinstance(raw, list) and len(raw) == recipe["replicates"], "raw needs three readings")
    for i, reading in enumerate(raw):
        with record(f"raw[{i}]"):
            timestamp(reading, "timestamp")
            settings = reading["settings"]
            for key, expected in (("adc_max", ADC_MAX), ("dark_offset_counts", DARK_COUNTS),
                                  ("reference_counts", BLANK_COUNTS)):
                require(settings[key] == expected, f"settings.{key} differs from the instrument")
            noise = settings["noise_sd_counts"]
            require(type(noise) in (int, float) and noise >= 0, "settings.noise_sd_counts is invalid")
    with record("raw"):
        return _payload(raw, cal, sample, prep, recipe)


def validate_calibration(cal):
    with record("initial.calibration"):
        require(cal["instrument_profile"] == PROFILE["instrument_profile"], "instrument_profile mismatch")
        standards = cal["standards"]
        require(isinstance(standards, list) and len(standards) == len(STANDARDS_MG_L),
                "standards are incomplete")
        means = []
        for index, (standard, concentration) in enumerate(zip(standards, STANDARDS_MG_L)):
            with record(f"standards[{index}]"):
                require(standard["concentration_mg_l"] == concentration, "concentration_mg_l mismatch")
                _, finding = _reading_evidence(standard["raw"], cal, f"std-{concentration}", None, RECIPE)
                observed = mean(finding["absorbances"])
                require(number_matches(standard["mean_absorbance"], observed), "mean_absorbance mismatch")
                residual = observed - (cal["slope"] * concentration + cal["intercept"])
                require(number_matches(standard["residual_absorbance"], residual), "residual_absorbance mismatch")
                means.append(observed)
        slope, intercept = linear_regression(STANDARDS_MG_L, means)
        for key, value in (("slope", slope), ("intercept", intercept), ("low", min(means)), ("high", max(means))):
            require(number_matches(cal[key], value), f"{key} differs from retained standards")


def _check_approval(approval, proposal, original, cal, direct_id, factor):
    require(approval["origin"] == direct_id, "origin differs from direct task ID")
    require(approval["protocol"] == proposal["protocol"], "protocol differs from original proposal")
    timestamp(approval, "approved_at")
    require(type(approval["factor"]) in (int, float) and math.isclose(approval["factor"], factor),
            "factor differs from actual preparation volumes")
    # Historical proposals authorized only a twofold preparation. New proposals
    # name both permitted factors and bind the decision to the finding.
    require(approval["factor"] in (2, 4) and approval["factor"] in proposal.get("factors", [2]),
            "factor is outside the proposed protocol")
    if approval["factor"] != 2 or "parent_sample_id" in approval or "evidence" in approval:
        require(approval["parent_sample_id"] == original, "parent_sample_id differs from the direct vial")
        evidence = approval["evidence"]
        with record("evidence"):
            require(evidence["calibration_id"] == cal["id"], "calibration_id differs from frozen fit")
            require(evidence["upper_standard"] == cal["high"], "upper_standard differs from frozen fit")
            _match_absorbances(evidence["readings"], proposal["readings"], "readings")


def _match_absorbances(saved, observed, field):
    require(isinstance(saved, list) and len(saved) == len(observed)
            and all(number_matches(x, y) for x, y in zip(saved, observed)), f"{field} differs from raw readings")


def _check_finding(saved, observed):
    for key in ("in_range", "above_range"):
        require(saved[key] is observed[key], f"finding.{key} differs from raw readings")
    _match_absorbances(saved["absorbances"], observed["absorbances"], "finding.absorbances")


def _measurement(measurement, task, cal, sample, prep, recipe, factor):
    data = measurement["input"]
    require(data["sample_id"] == sample, "input.sample_id mismatch")
    require(data["preparation"] == prep, "input.preparation differs from task preparation")
    payload, finding = _reading_evidence(measurement["raw"], cal, sample, prep, recipe)
    require(data["calibration"] == payload["calibration"], "input.calibration differs from frozen fit")
    _match_absorbances(data["absorbances"], payload["absorbances"], "input.absorbances")
    if prep is not None or "finding" in measurement:
        _check_finding(measurement["finding"], finding)
    if prep is not None or "revision" in measurement:
        require(measurement["revision"] == task["revision"], "revision differs from task revision")
    if prep is not None or "calibration_id" in measurement:
        require(measurement["calibration_id"] == cal["id"], "calibration_id differs from frozen fit")

    result = task["result"]
    if prep is not None or "result" in measurement:
        saved = measurement["result"]
        require(isinstance(saved, dict) and isinstance(result, dict), "result must be an object")
        for key in sorted(saved.keys() | result.keys()):
            require(key in saved and key in result and saved[key] == result[key],
                    f"result.{key} differs between task and measurement")
    require(result["sample_id"] == sample, "result.sample_id mismatch")
    require(result["calibration_id"] == cal["id"], "result.calibration_id mismatch")
    if not finding["in_range"]:
        require(result["status"] == "review" and result["concentration_mg_l"] is None,
                "result must withhold concentration_mg_l for out-of-range readings")
    else:
        require(result["status"] == "ok", "result.status disagrees with observed range")
        diluted = (mean(finding["absorbances"]) - cal["intercept"]) / cal["slope"]
        require(number_matches(result["concentration_mg_l"], diluted * factor),
                "result.concentration_mg_l differs from detector counts and preparation")
        if prep is not None:
            for key, value in (("factor", factor), ("diluted_mg_l", diluted)):
                require(number_matches(result[key], value), f"result.{key} differs from actual volumes or counts")
            require(result["parent_id"] == prep["parent_id"], "result.parent_id differs from preparation")
            require(result["preparation_id"] == prep["id"], "result.preparation_id differs from preparation")
    return finding


def validate_measurements(bundle, recipes):
    direct, child, initial = bundle["direct"], bundle["followup"], bundle["initial"]
    cal = initial["calibration"]
    with record("initial"):
        original = text_field(initial["input"], "sample_id")
        finding = _measurement(initial, direct, cal, original, None, recipes[0], 1)
    with record("direct"):
        require(direct.get("sample_id", original) == original, "sample_id differs from initial.input.sample_id")
        require(direct.get("preparation") is None and direct.get("parent_id") is None,
                "original direct task cannot have a preparation or parent_id")
        _check_finding(direct["finding"], finding)
        require(finding["above_range"], "finding must support the approved above-range follow-up")
        proposal = direct["proposal"]
        require(proposal["protocol"] == PROFILE["protocol"], "proposal.protocol mismatch")
        require(proposal["upper_standard"] == cal["high"], "proposal.upper_standard mismatch")
        require(proposal.get("calibration_id", cal["id"]) == cal["id"], "proposal.calibration_id mismatch")
        _match_absorbances(proposal["readings"], finding["absorbances"], "proposal.readings")
    with record("followup"):
        prep = child["preparation"]
        with record("preparation"):
            sample = text_field(prep, "sample_id")
            factor = validate_preparation(sample, prep)
            require(prep["parent_id"] == original, "parent_id differs from original vial")
        approval = child["approval"]
        with record("approval"):
            _check_approval(approval, proposal, original, cal, direct["id"], factor)
        with record("measurement"):
            _measurement(child["measurement"], child, cal, sample, prep, recipes[1], factor)
        if "replay" in child:
            replay = child["replay"]
            require(replay["parent_matches"] is True and replay["child_matches"] is True
                    and replay["calibration_id"] == cal["id"], "replay is inconsistent with a retained match")
        if "score" in child:
            require(child["result"]["status"] == "ok" and
                    child["score"]["predicted_mg_l"] == child["result"]["concentration_mg_l"],
                    "score.predicted_mg_l differs from the saved estimate")
