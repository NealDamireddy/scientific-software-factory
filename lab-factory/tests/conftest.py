import pytest


@pytest.fixture
def uvvis_lab_dict():
    return {
        "id": "emory-biophys",
        "name": "Emory Biophysics",
        "instruments": [{
            "id": "uvvis-1",
            "name": "UV-visible spectrophotometer",
            "model": "SP-550",
            "firmware": "2.3.1",
            "notes": "Teaching instrument for absorbance measurements.",
            "parameters": [
                {"name": "wavelength", "unit": "nm", "minimum": 400, "maximum": 700},
                {"name": "temperature", "unit": "K", "minimum": 278.15, "maximum": 303.15},
                {"name": "integration_time", "unit": "s", "minimum": 0.1, "maximum": 10},
            ],
            "commands": [
                {"name": "read_absorbance", "required": ["wavelength"], "optional": ["integration_time"]},
                {"name": "set_temperature", "required": ["temperature"], "optional": []},
            ],
        }],
        "documents": [{
            "id": "sop-cuvette", "kind": "sop", "title": "Cuvette handling",
            "source": "Teaching lab SOP", "text": "Rinse the cuvette and keep the optical faces clean.",
        }],
    }


@pytest.fixture
def b12_experiment_dict():
    return {
        "id": "b12-vial-a", "lab_id": "emory-biophys", "title": "Vitamin B12 absorbance",
        "goal": "Measure absorbance of the reference solution in vial A.",
        "instrument_ids": ["uvvis-1"],
        "documents": [{
            "id": "b12-protocol", "kind": "sop", "title": "Vial A protocol",
            "source": "Experiment notebook", "text": "Use the labeled reference solution in vial A.",
        }],
    }
