"""Pin the exact research instructions sent to a worker, independently of display metadata."""

import hashlib
import json


def wire_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def text_field(record, key, max_length):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"Invalid {key} in the worker briefing.")
    return value


def pin_skills(skills):
    if not isinstance(skills, list) or len(skills) > 32:
        raise ValueError("Provide at most 32 enabled skills.")
    pinned, seen = [], set()
    total_bytes = 0
    for item in skills:
        if not isinstance(item, dict):
            raise ValueError("Invalid enabled skill.")
        skill = {
            key: text_field(item, key, limit) for key, limit in
            (("id", 128), ("name", 256), ("whenToUse", 4096), ("instructions", 32768))
        }
        if skill["id"] in seen:
            raise ValueError("Each enabled skill must have a unique ID.")
        seen.add(skill["id"])
        stage = item.get("stage")
        if stage is not None:
            if stage not in ("start", "result", "repeat"):
                raise ValueError("Invalid skill stage.")
            skill["stage"] = stage
        body = wire_json([skill["id"], skill["name"], skill["whenToUse"], skill["instructions"], stage]).encode()
        total_bytes += len(body)
        if total_bytes > 96 * 1024:
            raise ValueError("Enabled skills exceed the 96 KiB delivery limit.")
        version = hashlib.sha256(body).hexdigest()
        if item.get("version", version) != version:
            raise ValueError("The pinned skill version does not match its instructions.")
        pinned.append({**skill, "version": version})
    return pinned
