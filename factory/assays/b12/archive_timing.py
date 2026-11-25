"""Check causal ordering of the events retained in a completed B12 archive."""
from datetime import datetime
from itertools import chain

from factory.assays.b12.archive_measurements import record, require, text_field


def _reading_events(path, raw):
    for index, reading in enumerate(raw):
        yield f"{path}.raw[{index}]", reading, "timestamp"


def _task_events(role, task, measurement):
    yield role, task, "created"
    measurement_path = "initial" if role == "direct" else "followup.measurement"
    attempts = task.get("acquisition_attempts", [])

    # Earlier failures can retain malformed detector output. Their journal
    # records when the failed attempt ran, independently of those readings.
    for index, previous in enumerate(attempts[:-1]):
        path = f"{role}.acquisition_attempts[{index}]"
        yield path, previous, "started_at"
        if previous.get("raw") or "acquired_at" in previous:
            yield path, previous, "acquired_at"
        yield path, previous, "finished_at"

    if attempts:
        path = f"{role}.acquisition_attempts[{len(attempts) - 1}]"
        current = attempts[-1]
        yield path, current, "started_at"
    if role == "direct":
        for index, standard in enumerate(measurement["calibration"]["standards"]):
            yield from _reading_events(f"initial.calibration.standards[{index}]", standard["raw"])
    yield from _reading_events(measurement_path, measurement["raw"])
    if attempts:
        yield path, current, "acquired_at"
    # The historical direct acquisition has raw timestamps but no result time.
    if role == "followup" or "time" in measurement:
        yield measurement_path, measurement, "time"
    if attempts:
        yield path, current, "finished_at"


def validate_timing(bundle):
    direct, child = bundle["direct"], bundle["followup"]
    events = chain(
        _task_events("direct", direct, bundle["initial"]),
        [("followup.approval", child["approval"], "approved_at")],
        _task_events("followup", child, child["measurement"]),
    )
    previous = None
    for path, data, key in events:
        with record(path):
            value = text_field(data, key)
            try:
                current = datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"{key} requires an ISO 8601 timestamp") from error
            require(current.utcoffset() is not None, f"{key} requires a timezone")
            if previous is not None and current < previous:
                raise ValueError(f"{key} precedes {previous_path}")
        previous = current
        previous_path = f"{path}.{key}"
