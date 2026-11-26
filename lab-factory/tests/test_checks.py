from dataclasses import replace

import pytest

from labfactory.artifacts import (
    ARTIFACT_EXAMPLES, Action, Amount, Procedure, ProcedureStep, RunPlan, RunStep,
    Setting, parse_artifact,
)
from labfactory.checks import all_passed, check_artifact, find_text_quantities
from labfactory.context import experiment_from_dict, lab_from_dict


@pytest.fixture
def context(uvvis_lab_dict, b12_experiment_dict):
    return lab_from_dict(uvvis_lab_dict), experiment_from_dict(b12_experiment_dict)


def run_plan(*settings, command="read_absorbance", instrument_id="uvvis-1"):
    return RunPlan(instrument_id, (RunStep(command, settings),))


def procedure(*, text="Read the sample.", citations=("sop-cuvette",), action=None, amounts=()):
    return Procedure((ProcedureStep(text, citations, action, amounts),))


def result_named(results, name):
    return next(result for result in results if result.name == name)


def assert_failure(results, name, detail):
    result = result_named(results, name)
    assert not result.passed
    assert detail in result.detail


def test_valid_examples_pass(context):
    assert not all_passed([])
    for kind, payload in ARTIFACT_EXAMPLES.items():
        assert all_passed(check_artifact(parse_artifact(kind, payload), *context))


def test_limits_are_inclusive(context):
    for value in (400, 700):
        assert all_passed(check_artifact(run_plan(Setting("wavelength", value, "nm")), *context))
    for value in (399.9, 700.0004):
        results = check_artifact(run_plan(Setting("wavelength", value, "nm")), *context)
        assert_failure(results, "step 1: wavelength", f"{value} nm is outside [400, 700] nm")


@pytest.mark.parametrize(("temperature", "passes"), [(5, True), (30, True), (31, False)])
def test_celsius_setting_against_kelvin_limit(context, temperature, passes):
    plan = run_plan(Setting("temperature", temperature, "degC"), command="set_temperature")
    assert all_passed(check_artifact(plan, *context)) == passes


@pytest.mark.parametrize(("ms", "passes"), [(500, True), (100, True), (11000, False)])
def test_unit_converts_before_comparing(context, ms, passes):
    plan = run_plan(Setting("wavelength", 550, "nm"), Setting("integration_time", ms, "ms"))
    assert all_passed(check_artifact(plan, *context)) == passes


def test_converted_large_integer_outside_limit_is_not_rounded_to_boundary(context):
    lab, experiment = context
    instrument = lab.instruments[0]
    boundary = 9007199254740992
    wavelength = replace(instrument.parameter("wavelength"), maximum=boundary, unit="um")
    lab = replace(lab, instruments=(replace(instrument, parameters=(wavelength,)),))
    for extra, passes in ((0, True), (1, False)):
        plan = run_plan(Setting("wavelength", 1000 * boundary + extra, "nm"))
        assert all_passed(check_artifact(plan, lab, experiment)) == passes


@pytest.mark.parametrize(
    ("setting", "detail"),
    [(Setting("wavelenght", 550, "nm"), "unknown parameter"),
     (Setting("wavelength", 550, "nanometers"), "unknown unit"),
     (Setting("wavelength", 550, "mL"), "dimension")],
)
def test_unknown_unit_and_parameter_fail_closed(context, setting, detail):
    results = check_artifact(run_plan(setting), *context)
    assert_failure(results, f"step 1: {setting.parameter}", detail)


def test_commands_must_exist_and_be_complete(context):
    wavelength = Setting("wavelength", 550, "nm")
    unknown = run_plan(wavelength, command="read_absorbence")
    assert_failure(check_artifact(unknown, *context), "step 1: command", "unknown command read_absorbence on uvvis-1")
    missing = run_plan(Setting("integration_time", 1, "s"))
    assert_failure(check_artifact(missing, *context), "step 1: command", "missing required setting wavelength")
    extra = run_plan(wavelength, Setting("temperature", 25, "degC"))
    assert_failure(check_artifact(extra, *context), "step 1: temperature", "not accepted by read_absorbance")


def test_duplicate_settings_fail_for_both_kinds(context):
    settings = (Setting("wavelength", 550, "nm"), Setting("wavelength", 600, "nm"))
    plan = run_plan(*settings)
    action = Action(plan.instrument_id, plan.steps[0].command, settings)
    for artifact in (plan, procedure(action=action)):
        results = check_artifact(artifact, *context)
        assert_failure(results, "step 1: command", "duplicate setting wavelength")
        duplicates = [r for r in results if r.name == "step 1: wavelength"]
        assert len(duplicates) == 2 and all(not r.passed for r in duplicates)
    separate_steps = RunPlan("uvvis-1", tuple(RunStep("read_absorbance", (s,)) for s in settings))
    assert all_passed(check_artifact(separate_steps, *context))


def test_instrument_not_in_experiment_fails(context):
    lab, experiment = context
    plan = run_plan(Setting("wavelength", 550, "nm"), instrument_id="epr-1")
    # Missing from the lab, missing from the experiment, or missing from both.
    for lab_context, exp_context in (
        (lab, replace(experiment, instrument_ids=("epr-1",))),
        (replace(lab, instruments=(replace(lab.instruments[0], id="epr-1"),)), experiment),
        (lab, experiment),
    ):
        results = check_artifact(plan, lab_context, exp_context)
        assert_failure(results, "instrument listed", "epr-1")
        assert_failure(results, "step 1: wavelength", "unknown instrument")


def test_procedure_citations(context):
    for citations, detail in (((), "no citation"), (("sop-cuvette", "sop-missing"), "unknown document sop-missing")):
        results = check_artifact(procedure(citations=citations), *context)
        assert_failure(results, "step 1: citations", detail)
    assert all_passed(check_artifact(procedure(citations=("sop-cuvette", "b12-protocol")), *context))


def test_citations_require_a_unique_pinned_document(context):
    lab, experiment = context
    duplicate = replace(experiment.documents[0], id=lab.documents[0].id)
    experiment = replace(experiment, documents=(*experiment.documents, duplicate))
    results = check_artifact(procedure(citations=("b12-protocol", "sop-cuvette")), lab, experiment)
    assert_failure(results, "step 1: citations", "ambiguous document sop-cuvette")
    assert all_passed(check_artifact(procedure(citations=("b12-protocol",)), lab, experiment))


def test_citation_check_detail_preserves_id_boundaries(context):
    lab, experiment = context
    lab = replace(lab, documents=tuple(
        replace(lab.documents[0], id=id) for id in ("Smith", "2022", "Smith, 2022")
    ))
    for citations, detail in [
        (("Smith", "2022"), "Smith, 2022"),
        (("Smith, 2022",), '"Smith, 2022"'),
    ]:
        result = result_named(check_artifact(procedure(citations=citations), lab, experiment), "step 1: citations")
        assert result.passed and result.detail == detail


def test_values_in_text_fail(context):
    action = Action("uvvis-1", "read_absorbance", (Setting("wavelength", 550, "nm"),))
    for candidate in (None, action):
        results = check_artifact(procedure(text="Measure at 800 nm.", action=candidate), *context)
        assert_failure(results, "step 1: text values", "800 nm")
        assert_failure(results, "step 1: text values", "put instrument values in the action and hand-measured values in amounts")
        if candidate:
            assert result_named(results, "step 1: wavelength").passed
    for text in ("Incubate for 5 minutes.", "Pipette 1 mL of sample."):
        assert not all_passed(check_artifact(procedure(text=text), *context))
    for text in ("Rinse the cuvette twice.", "Repeat 3 times."):
        assert all_passed(check_artifact(procedure(text=text), *context))


def test_find_text_quantities():
    assert find_text_quantities("Heat to 25 °C, then read at 550nm for 2 s") == ["25 °C", "550nm", "2 s"]
    assert find_text_quantities("2 steps, 5 nmol, 1 au, 8 nmé, 16 kelvins") == []
    symbols = "nm um uL mL L ms s min h K degC mT G T AU °C µL μL µm μm"
    words = ("nanometers micrometer microliters milliliters liter milliseconds seconds sec minute "
             "mins hour hrs kelvin celsius gauss tesla millitesla")
    quantities = [f"0.125{token}" for token in symbols.split() + words.upper().split()]
    assert find_text_quantities(", ".join(quantities)) == quantities


def test_amount_units_fail_closed(context):
    results = check_artifact(procedure(amounts=(Amount("sample", 1, "cups"),)), *context)
    assert_failure(results, "step 1: amount sample", "unknown unit cups")
