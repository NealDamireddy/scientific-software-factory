import json
from pathlib import Path

import pytest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(autouse=True)
def default_reviewer_mode(monkeypatch):
    monkeypatch.delenv("LABFACTORY_PUBLIC_REVIEW", raising=False)


@pytest.fixture
def uvvis_lab_dict():
    return json.loads((EXAMPLES / "uvvis-lab.json").read_text(encoding="utf-8"))


@pytest.fixture
def b12_experiment_dict():
    return json.loads((EXAMPLES / "b12-experiment.json").read_text(encoding="utf-8"))


@pytest.fixture
def store(tmp_path):
    from labfactory.store import Store

    with Store(tmp_path / "lf.db") as db:
        yield db
