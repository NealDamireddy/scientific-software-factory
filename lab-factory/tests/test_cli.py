from copy import deepcopy
from pathlib import Path

import pytest

from labfactory.agent import AgentTools
from labfactory.artifacts import ARTIFACT_EXAMPLES
from labfactory.cli import main
from labfactory.store import Store

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def operator(tmp_path, capsys):
    db = tmp_path / "factory.db"

    def cli(*args):
        return main(["--db", str(db), *args])

    assert cli("lab", "put", str(EXAMPLES / "uvvis-lab.json")) == 0
    assert cli("experiment", "put", str(EXAMPLES / "b12-experiment.json")) == 0
    assert capsys.readouterr().out.splitlines() == ["emory-biophys revision 1", "b12-vial-a revision 1"]
    with Store(db) as store:
        yield cli, AgentTools(store)


def create(cli, kind):
    assert cli("wo", "create", "b12-vial-a", "--kind", kind, "--objective", "Read vial A") == 0


def submit(agent, artifact, worker="codex"):
    agent.claim_work_order("WO-1", worker)
    response = agent.submit_artifact("WO-1", worker, artifact)
    assert response["passed"]
    return response


def test_end_to_end(operator, capsys):
    cli, agent = operator
    create(cli, "run_plan")
    assert capsys.readouterr().out.strip() == "WO-1"
    artifact = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    settings = artifact["steps"][0]["settings"]
    settings[0]["value"] = 550.0004
    settings.append({"parameter": "integration_time", "value": 500, "unit": "ms"})
    artifact["steps"].append({"command": "set_temperature", "settings": [
        {"parameter": "temperature", "value": 30, "unit": "degC"}]})
    submission = submit(agent, artifact)
    assert cli("wo", "list", "--status", "in_review") == 0
    assert "WO-1" in capsys.readouterr().out
    assert cli("wo", "show", "WO-1") == 0
    review = capsys.readouterr().out
    assert "WO-1 run_plan in_review" in review
    assert "awaiting review: submission 1" in review
    assert f"submission 1 by codex · digest {submission['artifact_digest'][:12]} · passed" in review
    assert ("Step 1\n  On uvvis-1: read_absorbance (wavelength 550.0004 nm, integration_time 500 ms)\n\n"
            "Step 2\n  On uvvis-1: set_temperature (temperature 30 degC)") in review
    assert cli("wo", "approve", "WO-1", "--submission", "1", "--by", "Neal") == 0
    assert cli("wo", "show", "WO-1") == 0
    released = capsys.readouterr().out
    assert "released: submission 1 by Neal" in released
    assert "lab emory-biophys revision 1" in released
    assert submission["artifact_digest"] in released


def test_show_renders_procedure(operator, capsys):
    cli, agent = operator
    create(cli, "procedure")
    submit(agent, ARTIFACT_EXAMPLES["procedure"])
    assert cli("wo", "show", "WO-1") == 0
    review = capsys.readouterr().out
    assert "submission 1 by codex" in review and "awaiting review: submission 1" in review
    first, rest = review.split("Step 1\n", 1)[1].split("Step 2\n", 1)
    second, third = rest.split("Step 3\n", 1)
    assert "Notes, not checked by code: Rinse the cuvette twice with buffer." in first
    assert "Citations: sop-cuvette" in first
    assert "Amounts, not checked against instrument limits: sample 1 mL" in second
    assert "Citations: b12-protocol" in second
    assert "On uvvis-1: read_absorbance (wavelength 550 nm)" in third
    assert "Citations: sop-cuvette" in third


def test_cli_errors_exit_1(operator, capsys, tmp_path):
    cli, agent = operator
    create(cli, "run_plan")
    assert cli("wo", "approve", "WO-1", "--submission", "1", "--by", "Neal") == 1
    assert capsys.readouterr().err.startswith("error: ")
    submit(agent, ARTIFACT_EXAMPLES["run_plan"])
    assert cli("wo", "reject", "WO-1", "--submission", "1", "--by", "Neal", "--reason", "revise") == 0
    submit(agent, ARTIFACT_EXAMPLES["run_plan"], "claude")
    assert cli("wo", "approve", "WO-1", "--submission", "1", "--by", "Neal") == 1
    assert capsys.readouterr().err.startswith("error: submission 1 is not the latest")
    assert cli("lab", "put", str(tmp_path / "missing")) == 1
    assert capsys.readouterr().err.startswith("error: ")
