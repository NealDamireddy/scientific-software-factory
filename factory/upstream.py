"""Normalize a project Work Order into an executable order, retaining its planning identifier."""
import csv
from pathlib import Path
import re
from .context import read_json, validate_order


def adapt(template, number, title):
    if not re.fullmatch(r"WO-[1-9][0-9]*", number) or not title.strip():
        raise ValueError("Expected an 8090 Work Order ID and title")
    order = dict(template, origin="8090", upstream_id=number, objective=title.strip() + ". " + template["objective"])
    validate_order(order)
    return order


def from_export(path, number, template):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = {key.lower().strip(): value for key,value in row.items()}
            identifier = normalized.get("id") or normalized.get("work order id") or normalized.get("number")
            if identifier in (number,number.removeprefix("WO-")):
                return adapt(read_json(template), number, normalized.get("name") or normalized.get("title") or "")
    raise ValueError("Expected ID/Number and Name/Title columns containing " + number)
