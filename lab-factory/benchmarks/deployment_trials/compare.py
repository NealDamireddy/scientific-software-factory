"""Verify two or more deployment trial receipts against their canonical JSON outputs."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


HASH = re.compile(r"[a-f0-9]{64}")
FIELDS = (
    "workload_sha256", "request_sequence_sha256", "logical_request_sequence_sha256",
    "outcome_sha256", "outcome_v2_sha256",
)


def read_receipt(path):
    body = json.loads(path.read_text(encoding="utf-8"))
    # Variant drivers may bundle the complete receipt with lifecycle measurements.
    if isinstance(body, dict) and "acceptance" in body:
        body = body["acceptance"]
    if not isinstance(body, dict) or not all(isinstance(body.get(k), dict) for k in ("outcome", "outcome_v2")):
        raise ValueError("missing a canonical outcome")
    if not all(isinstance(body.get(k), str) and HASH.fullmatch(body[k]) for k in FIELDS):
        raise ValueError("missing or invalid SHA-256")
    for outcome in ("outcome", "outcome_v2"):
        encoded = json.dumps(
            body[outcome], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != body[outcome + "_sha256"]:
            raise ValueError(f"{outcome} differs from its claimed digest")
    reopened = body.get("verification", {})
    downtime = body.get("downtime", {})
    if not isinstance(reopened, dict) or not isinstance(downtime, dict):
        raise ValueError("invalid verification or downtime record")
    if not isinstance(body.get("access_mode"), str) or not body["access_mode"]:
        raise ValueError("missing access mode")
    verified = reopened.get("passed") is True and all(
        reopened.get(key) == body[key] for key in ("outcome_sha256", "outcome_v2_sha256")
    )
    return {
        **{k: body[k] for k in FIELDS},
        "access_mode": body["access_mode"],
        "verified": verified,
        "offline_observed": downtime.get("confirmed") is True,
    }


def fixture_hash():
    fixtures = Path(__file__).with_name("fixtures")
    manifest = json.loads((fixtures / "manifest.json").read_bytes())
    digest = hashlib.sha256((fixtures / "workload.json").read_bytes()).hexdigest()
    if digest != manifest["workload_sha256"]:
        raise ValueError("workload does not match its manifest")
    return digest


def compare(receipts):
    """Keep reachability during failure separate from equivalence of successfully observed output."""
    if len(receipts) < 2:
        raise ValueError("supply at least two distinct deployment receipts")
    matches = {k: len({r[k] for r in receipts.values()}) == 1 for k in FIELDS}
    all_verified = all(r["verified"] for r in receipts.values())
    pinned_workload = fixture_hash()
    all_pinned = all(r["workload_sha256"] == pinned_workload for r in receipts.values())
    return {
        "parity": all(matches.values()) and all_verified and all_pinned,
        "pinned_workload_sha256": pinned_workload,
        "all_used_pinned_workload": all_pinned,
        "matching_hashes": matches,
        "all_verified": all_verified,
        "deployments": dict(sorted(receipts.items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="+", metavar="NAME=STATE.json")
    args = parser.parse_args()
    receipts = {}
    for arg in args.receipts:
        name, sep, path = arg.partition("=")
        if not sep or not name or not path or name in receipts:
            parser.error("use a distinct NAME=STATE.json for each deployment")
        try:
            receipts[name] = read_receipt(Path(path))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            parser.error(f"{name}: {exc}")
    try:
        result = compare(receipts)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["parity"] else 1


if __name__ == "__main__":
    sys.exit(main())
