"""Regression checks for cross-deployment acceptance receipts."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("trial_comparison", Path(__file__).with_name("compare.py"))
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def _receipt(path):
    digest = sha256(b'{"value":2}').hexdigest()
    payload = {"outcome": {"value": 2}, "outcome_sha256": digest, "workload_sha256": comparison.fixture_hash(),
               "request_sequence_sha256": "e" * 64, "access_mode": "public",
               "verification": {"passed": True, "outcome_sha256": digest}}
    details = {"sample_id": "sample-1", "unit": "mg/L"}
    full_hash = sha256(b'{"sample_id":"sample-1","unit":"mg/L"}').hexdigest()
    payload.update(outcome_v2=details, outcome_v2_sha256=full_hash, logical_request_sequence_sha256="4" * 64)
    payload["verification"]["outcome_v2_sha256"] = full_hash
    path.write_text(json.dumps(payload))
    return payload


def test_reachable_replica_and_full_outage_can_share_outputs(tmp_path):
    path = tmp_path / "a.json"
    body = _receipt(path)
    first = comparison.read_receipt(path)
    body.update(access_mode="private", downtime={"confirmed": True})
    path.write_text(json.dumps(body))
    second = comparison.read_receipt(path)
    result = comparison.compare({"replicas": first, "single": second})
    assert result["parity"]
    assert not first["offline_observed"] and second["offline_observed"]


def test_modified_output_is_rejected_even_if_digest_field_matches_other_topology(tmp_path):
    path = tmp_path / "a.json"
    body = _receipt(path)
    body["outcome"]["value"] = 3
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="digest"):
        comparison.read_receipt(path)


def test_same_result_requires_same_requests_and_a_successful_reopen(tmp_path):
    path = tmp_path / "a.json"
    body = _receipt(path)
    first = comparison.read_receipt(path)
    body["request_sequence_sha256"] = "0" * 64
    body["verification"]["passed"] = False
    path.write_text(json.dumps(body))
    result = comparison.compare({"left": first, "right": comparison.read_receipt(path)})
    assert not result["parity"] and not result["all_verified"]
    assert result["matching_hashes"] == {
        "workload_sha256": True, "request_sequence_sha256": False, "logical_request_sequence_sha256": True,
        "outcome_sha256": True, "outcome_v2_sha256": True,
    }


def test_v1_agreement_alone_cannot_hide_replaced_scientific_evidence(tmp_path):
    path = tmp_path / "a.json"
    body = _receipt(path)
    body["outcome_v2"]["sample_id"] = "sample-2"
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="outcome_v2"):
        comparison.read_receipt(path)
