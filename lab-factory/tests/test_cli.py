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


@pytest.mark.parametrize(("kind", "example", "original", "conflict", "key"), [
    ("lab", "uvvis-lab.json", '"maximum": 700', '"maximum": 700, "maximum": 900', "maximum"),
    ("experiment", "b12-experiment.json", '"lab_id": "emory-biophys"',
     '"lab_id": "other", "lab_id": "emory-biophys"', "lab_id"),
])
def test_put_rejects_duplicate_json_fields(operator, tmp_path, capsys, kind, example, original, conflict, key):
    cli, _ = operator
    text = (EXAMPLES / example).read_text(encoding="utf-8")
    assert original in text
    invalid = tmp_path / example
    invalid.write_text(text.replace(original, conflict, 1), encoding="utf-8")
    assert cli(kind, "put", str(invalid)) == 1
    assert capsys.readouterr().err.strip() == f"error: duplicate JSON field {key!r}"
    assert cli(kind, "put", str(EXAMPLES / example)) == 0
    assert capsys.readouterr().out.rstrip().endswith("revision 1")


def test_list_and_show_see_committed_order_during_write(operator, tmp_path, capsys):
    cli, _ = operator
    create(cli, "run_plan")
    capsys.readouterr()
    with Store(tmp_path / "factory.db") as writer, writer.transaction() as connection:
        connection.execute("UPDATE work_orders SET status = 'in_progress' WHERE id = 'WO-1'")
        for args in [("list", "--status", "open"), ("show", "WO-1")]:
            assert cli("wo", *args) == 0
            assert "WO-1 run_plan open" in capsys.readouterr().out


def test_show_and_requeue_specific_claim(operator, capsys):
    cli, agent = operator
    create(cli, "run_plan")
    agent.claim_work_order("WO-1", "worker")
    assert cli("wo", "show", "WO-1") == 0
    assert "claim: 1" in capsys.readouterr().out.splitlines()
    assert cli("wo", "requeue", "WO-1", "--claim", "1", "--by", "Ada", "--reason", "Disconnected") == 0
    assert cli("wo", "show", "WO-1") == 0
    reopened = capsys.readouterr().out
    assert "WO-1 run_plan open" in reopened and "\nclaim: " not in reopened
    assert "requeued by Ada" in reopened and "Disconnected" in reopened
    agent.claim_work_order("WO-1", "worker")
    assert cli("wo", "requeue", "WO-1", "--claim", "1", "--by", "Ada", "--reason", "Stale") == 1
    assert "no longer active" in capsys.readouterr().err
    assert cli("wo", "show", "WO-1") == 0
    assert "claim: 2" in capsys.readouterr().out.splitlines()
