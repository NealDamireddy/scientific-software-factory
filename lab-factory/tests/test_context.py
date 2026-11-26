import copy
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from labfactory.context import ContextError, digest, experiment_from_dict, lab_from_dict, to_dict


def test_round_trip_and_digest_stable(uvvis_lab_dict, b12_experiment_dict):
    for data, parse in [(uvvis_lab_dict, lab_from_dict), (b12_experiment_dict, experiment_from_dict)]:
        record = parse(data)
        assert to_dict(record) == data
        expected = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert digest(record) == digest(parse(copy.deepcopy(data))) == expected
        assert isinstance(record.documents, tuple)
        with pytest.raises(FrozenInstanceError):
            record.id = "changed"
    lab = lab_from_dict(uvvis_lab_dict)
    instrument = lab.instrument("uvvis-1")
    assert instrument.command("read_absorbance").required == ("wavelength",)
    assert instrument.parameter("temperature").unit == "K"
    assert lab.document("sop-cuvette").kind == "sop"
    assert instrument.command("other") is None


def test_digest_changes_with_content(uvvis_lab_dict):
    original = digest(lab_from_dict(uvvis_lab_dict))
    uvvis_lab_dict["instruments"][0]["firmware"] = "2.3.2"
    assert digest(lab_from_dict(uvvis_lab_dict)) != original


@pytest.mark.parametrize("invalid", [
    "limits", "unit", "duplicate instruments", "duplicate documents", "duplicate commands",
    "duplicate parameters", "unknown required", "unknown optional", "document kind", "missing name",
    "nonfinite", "boolean", "required and optional", "unknown field",
])
def test_rejects_invalid_context(uvvis_lab_dict, invalid):
    d = uvvis_lab_dict
    inst = d["instruments"][0]
    p = inst["parameters"][0]
    if invalid.startswith("duplicate"):
        field = invalid.split()[1]
        values = (d if field in d else inst)[field]
        values.append(copy.deepcopy(values[0]))
    elif invalid.startswith("unknown ") and invalid != "unknown field":
        inst["commands"][0][invalid.split()[1]].append("slit_width")
    elif invalid == "required and optional":
        inst["commands"][0]["optional"].append("wavelength")
    elif invalid == "document kind":
        d["documents"][0]["kind"] = "blog"
    elif invalid == "missing name":
        del d["name"]
    elif invalid == "unknown field":
        d["ignored"] = "content"
    else:
        field, value = {
            "limits": ("minimum", 701), "unit": ("unit", "nanometers"),
            "nonfinite": ("maximum", float("nan")), "boolean": ("minimum", True),
        }[invalid]
        p[field] = value
    with pytest.raises(ContextError):
        lab_from_dict(d)


def test_requires_experiment_instruments(b12_experiment_dict):
    b12_experiment_dict["instrument_ids"] = []
    with pytest.raises(ContextError, match="instrument_ids"):
        experiment_from_dict(b12_experiment_dict)


def test_reference_ids_must_be_printable(uvvis_lab_dict):
    uvvis_lab_dict["documents"][0]["id"] = "sop\ncuvette"
    with pytest.raises(ContextError, match="printable"):
        lab_from_dict(uvvis_lab_dict)
