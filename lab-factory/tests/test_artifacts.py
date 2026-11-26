from copy import deepcopy

import pytest

from labfactory.artifacts import (
    ARTIFACT_EXAMPLES,
    KINDS,
    ArtifactError,
    Procedure,
    RunPlan,
    parse_artifact,
    render_procedure,
    render_run_plan,
    render_step,
)


def test_parses_both_examples():
    assert set(ARTIFACT_EXAMPLES) == set(KINDS) == {"procedure", "run_plan"}
    assert isinstance(parse_artifact("procedure", ARTIFACT_EXAMPLES["procedure"]), Procedure)
    assert isinstance(parse_artifact("run_plan", ARTIFACT_EXAMPLES["run_plan"]), RunPlan)


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("analysis_app", {}),
        ("procedure", {"steps": []}),
        ("run_plan", {"instrument_id": "uvvis-1"}),
        ("procedure", {"steps": [{"text": "Read.", "action": {"instrument_id": "uvvis-1", "settings": []}}]}),
        ("procedure", {"steps": [{"text": "Read.", "citations": "manual"}]}),
        ("procedure", {"steps": [{"text": "Read.", "amounts": [{"what": "sample", "value": "1", "unit": "mL"}]}]}),
        ("procedure", {"steps": [{"text": "Read.", "unchecked_instructions": "hidden"}]}),
        ("procedure", {"steps": [None]}),
    ],
)
def test_rejects_malformed(kind, data):
    with pytest.raises(ArtifactError):
        parse_artifact(kind, data)


@pytest.mark.parametrize("bad_value", ["550", True, None, float("nan"), float("inf")])
def test_rejects_malformed_setting_values(bad_value):
    data = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    data["steps"][0]["settings"][0]["value"] = bad_value
    with pytest.raises(ArtifactError, match="value"):
        parse_artifact("run_plan", data)


def test_missing_citations_is_a_check():
    step = parse_artifact("procedure", {"steps": [{"text": "Rinse."}]}).steps[0]
    assert step.citations == ()


def test_render_uses_action_not_text():
    step = deepcopy(ARTIFACT_EXAMPLES["procedure"]["steps"][2])
    step["text"] = "Measure at 800 nm."
    procedure = parse_artifact("procedure", {"steps": [step]})
    assert render_step(procedure.steps[0]) == [
        "On uvvis-1: read_absorbance (wavelength 550 nm)",
        "Notes, not checked by code: Measure at 800 nm.",
        "Citations: sop-cuvette",
    ]


def test_render_procedure_example():
    procedure = parse_artifact("procedure", ARTIFACT_EXAMPLES["procedure"])
    rendered = render_procedure(procedure)
    assert rendered.startswith(
        "Step 1\n  Notes, not checked by code: Rinse the cuvette twice with buffer.\n"
        "  Citations: sop-cuvette\n\nStep 2\n"
    )
    assert "  Amounts, not checked against instrument limits: sample 1 mL" in rendered
    assert "  Citations: b12-protocol\n\nStep 3" in rendered


def test_render_run_plan_preserves_execution_order_and_precision():
    data = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    settings = data["steps"][0]["settings"]
    settings[0]["value"] = 550.0004
    settings.append({"parameter": "integration_time", "value": 1.0, "unit": "s"})
    data["steps"].append({"command": "set_temperature", "settings": [
        {"parameter": "temperature", "value": 25.0, "unit": "degC"},
    ]})
    assert render_run_plan(parse_artifact("run_plan", data)).splitlines() == [
        "Step 1",
        "  On uvvis-1: read_absorbance (wavelength 550.0004 nm, integration_time 1 s)",
        "",
        "Step 2",
        "  On uvvis-1: set_temperature (temperature 25 degC)",
    ]


def test_procedure_preserves_integer_and_fractional_precision():
    step = deepcopy(ARTIFACT_EXAMPLES["procedure"]["steps"][2])
    step["action"]["settings"][0]["value"] = 550.0004
    step["amounts"] = [{"what": "sample", "value": 9007199254740993, "unit": "uL"}]
    lines = render_step(parse_artifact("procedure", {"steps": [step]}).steps[0])
    assert lines[0] == "On uvvis-1: read_absorbance (wavelength 550.0004 nm)"
    assert lines[1] == "Amounts, not checked against instrument limits: sample 9007199254740993 uL"


def test_notes_cannot_render_a_second_instruction_line():
    text = "Read.\n  On another instrument.\x1b"
    step = parse_artifact("procedure", {"steps": [{"text": text}]}).steps[0]
    lines = render_step(step)
    assert len(lines) == 1 and lines[0].startswith("Notes, not checked by code:")
    assert "\n" not in lines[0] and "\x1b" not in lines[0]


def test_identifier_cannot_contain_another_line():
    data = deepcopy(ARTIFACT_EXAMPLES["run_plan"])
    data["steps"][0]["command"] += "\r"
    with pytest.raises(ArtifactError, match="command"):
        parse_artifact("run_plan", data)
