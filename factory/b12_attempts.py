"""Journal a B12 instrument attempt in the same atomic record served by the task API."""
from datetime import datetime, timezone
import math
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def json_readings(value):
    """Retain nonfinite detector values as text in strict JSON, so assessment rejects them."""
    if isinstance(value, list):
        return [json_readings(item) for item in value]
    if isinstance(value, dict):
        return {key: json_readings(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


class Attempt:
    """The caller holds the Lab lock across acquisition or reconciliation."""

    def __init__(self, lab, task, record):
        self.lab = lab
        self.task_id = task["id"]
        self.record = record

    @classmethod
    def open(cls, lab, task, *, sample_id, calibration_id=None, settings, retry_of=None):
        history = task.get("acquisition_attempts", [])
        if retry_of is not None:
            if not isinstance(retry_of, str) or not retry_of:
                raise ValueError("retry_of must identify a rejected acquisition attempt")
            # Each rejected attempt can authorize only one successor.
            for item in history:
                if item.get("retry_of") == retry_of:
                    return cls(lab, task, item), False
            if (not history or history[-1]["id"] != retry_of
                    or history[-1]["status"] not in ("rejected", "interrupted")):
                raise ValueError("retry_of must identify the current rejected or interrupted attempt")
        elif history:
            return cls(lab, task, history[-1]), False

        record = dict(id=uuid.uuid4().hex, status="acquiring", started_at=now(),
                      sample_id=sample_id, preparation=task.get("preparation"), revision=task.get("revision"),
                      calibration_id=calibration_id, settings=settings, raw=[])
        if retry_of is not None:
            record["retry_of"] = retry_of
        lab.update(task["id"], acquisition_attempts=[*history, record],
                   acquisition_attempt_id=record["id"], acquisition_status="acquiring")
        return cls(lab, task, record), True

    def save(self, status, *, task_fields=None, **fields):
        task = self.lab.task(self.task_id)
        history = task["acquisition_attempts"]
        if history[-1]["id"] != self.record["id"]:
            raise ValueError("Acquisition attempt is no longer current")
        self.record = {**history[-1], **fields, "status": status}
        return self.lab.update(self.task_id, acquisition_attempts=[*history[:-1], self.record],
                               acquisition_status=status, **(task_fields or {}))

    def acquired(self, raw):
        self.save("acquired", raw=json_readings(raw), acquired_at=now())

    def reject(self, field, error):
        return self.save("rejected", finished_at=now(), failure={"field": field, "reason": str(error)[:1800]})

    def interrupted(self):
        return self.save("interrupted", finished_at=now(), failure={
            "field": "acquisition", "reason": "Acquisition interrupted before readings were saved",
        })


def record_direct_analysis(lab, task_id, *, revision=None, error=None):
    """Associate the caller's final analysis outcome with its previously collected counts."""
    with lab.lock:
        task = lab.task(task_id)
        history = task.get("acquisition_attempts")
        if task.get("parent_id") or not history or history[-1]["status"] != "collected":
            return task
        attempt = Attempt(lab, task, history[-1])
        if error is not None:
            return attempt.save("rejected", revision=task.get("revision"), finished_at=now(),
                                failure={"field": "analysis", "reason": str(error)[:1800]})
        if (revision is None or revision != task.get("revision") or task.get("status") != "verified"
                or not task.get("result") or task["result"].get("sample_id") != attempt.record["sample_id"]
                or task["result"].get("calibration_id") != attempt.record["calibration_id"]):
            raise ValueError("Direct analysis requires a saved result matching the verified release, sample and calibration")
        return attempt.save("completed", revision=revision, finished_at=now())
