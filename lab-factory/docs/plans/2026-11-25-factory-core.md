# Lab Factory Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core of a lab's software factory:
- versioned lab and experiment context, with instrument commands and limits
- work orders that pin that context
- checks for procedures and run plans
- release of a specific, fingerprinted submission by a named person
- an MCP server for coding agents and a CLI for people

**Architecture:** A standalone Python package in `lab-factory/` that uses SQLite through the standard library.
- Context records are frozen dataclasses with SHA-256 digests, stored as append-only revisions.
- Work orders pin revisions. Submissions are checked against those pinned revisions and fingerprinted.
- Procedures keep checked instrument actions apart from unchecked prose. People see actions only as the factory renders them.
- Agents reach the factory only through `AgentTools`, which the MCP server wraps. Approval exists only in the CLI.

**Tech Stack:** Python ≥3.11, uv, pytest, `mcp` (official Python SDK: `mcp.server.fastmcp.FastMCP`, `mcp.client.stdio`), sqlite3, argparse.

**Spec:** `lab-factory/docs/specs/2026-11-25-lab-factory-architecture-design.md`

## Global Constraints

- **Isolation.** All code lives under `lab-factory/`. It never imports from the repo's existing `factory/` package and never touches files outside `lab-factory/`.
- **Branch.** Work on a dedicated branch, `lab-factory/core`, never on `main`. Run every command from `lab-factory/`.
- **Python and dependencies.** `requires-python = ">=3.11"`. The only runtime dependency is `mcp`. The only dev dependency is `pytest`.
- **Unit spellings,** exactly: `nm`, `um`, `uL`, `mL`, `L`, `ms`, `s`, `min`, `h`, `K`, `degC`, `mT`, `G`, `T`, `AU`.
- **Document kinds,** exactly: `sop`, `manual`, `standard`, `paper`, `note`.
- **Work orders.** Kinds, exactly: `procedure`, `run_plan`. Statuses, exactly: `open`, `in_progress`, `in_review`, `released`.
- **Limits and failures.** Limits are inclusive. An unknown unit, parameter, command, instrument or citation produces a failing `CheckResult`. It is never skipped.
- **Approval.** No agent-facing code path (`AgentTools`, the MCP server) can approve or release. Approval always names a submission number.
- **Trust assumption.** The core assumes a trusted local operator. It does not defend against an agent that has shell access as the same computer user. The README says so, using the exact text given in Task 8.

## Review Focus

1. **An instrument value written in the prose.**
   - "Measure at 800 nm" with no action fails.
   - An action of 550 nm with the text "Measure at 800 nm" also fails, and the rendered instruction shows 550 nm from the action.
   - Tests: Task 5, `test_values_in_text_fail`; Task 4, `test_render_uses_action_not_text`.
2. **Approving a submission other than the one reviewed.** If submission 2 is now in review, an approval naming submission 1 is refused. Test: Task 6, `test_approval_names_reviewed_submission`.
3. **A command the instrument doesn't have, or a missing required setting.** Each fails with a readable detail. Test: Task 5, `test_commands_must_exist_and_be_complete`.
4. **Lab revised after a work order is created.** Checks use the pinned revision, so a limit widened later can't make an old order pass. Test: Task 6, `test_checks_use_pinned_lab_revision`.
5. **Celsius setting against a Kelvin limit.** `30 degC` against `[278.15, 303.15] K` passes, and `31 degC` fails. Test: Task 5, `test_celsius_setting_against_kelvin_limit`.

---

### Task 1: Project scaffold and units

**Files:**
- Create: `lab-factory/pyproject.toml`, `lab-factory/src/labfactory/__init__.py`, `lab-factory/src/labfactory/units.py`
- Test: `lab-factory/tests/test_units.py`

**Interfaces:**
- Produces: `class UnitError(ValueError)`; `convert(value: float, from_unit: str, to_unit: str) -> float`; `is_known_unit(unit: str) -> bool`.

- [ ] **Step 1: Create `pyproject.toml`.**
  - name `labfactory`, version `0.1.0`
  - hatchling with the src layout
  - `requires-python = ">=3.11"` and `dependencies = ["mcp>=1,<2"]` for the specified FastMCP v1 import
  - dev dependency group `["pytest"]`
  - `[project.scripts] labfactory = "labfactory.cli:main"`

  Then run `uv sync`. Expected: it finishes with no errors.

- [ ] **Step 2: Write the failing tests**

```python
import pytest
from labfactory.units import convert, is_known_unit, UnitError

def test_conversions():
    assert convert(550, "nm", "nm") == 550
    assert convert(1000, "uL", "mL") == pytest.approx(1.0)
    assert convert(2, "min", "s") == pytest.approx(120)
    assert convert(25, "degC", "K") == pytest.approx(298.15)
    assert convert(300, "K", "degC") == pytest.approx(26.85)
    assert convert(10, "G", "mT") == pytest.approx(1.0)
    assert convert(0.5, "T", "mT") == pytest.approx(500)

def test_dimension_mismatch_and_unknown_unit():
    with pytest.raises(UnitError, match="dimension"):
        convert(1, "nm", "mL")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1, "furlong", "nm")
    assert is_known_unit("AU") and not is_known_unit("au")
```

- [ ] **Step 3: Run `uv run pytest tests/test_units.py -v`.** Expected: FAIL with an import error.

- [ ] **Step 4: Implement `units.py`.** Map each unit to `(dimension, scale, offset)`, where canonical value = value × scale + offset. Unit spellings are case-sensitive.
  - length: canonical `nm`, with `um` = 1000
  - volume: canonical `mL`, with `uL` = 0.001 and `L` = 1000
  - time: canonical `s`, with `ms`, `min` and `h`
  - temperature: canonical `K`, with `degC` = scale 1, offset 273.15
  - field: canonical `mT`, with `G` = 0.1 and `T` = 1000
  - absorbance: `AU` only

- [ ] **Step 5: Run the tests again.** Expected: PASS.

- [ ] **Step 6: Commit** with the message `feat(lab-factory): scaffold package and unit conversion`.

---

### Task 2: Context records, commands and digests

**Files:**
- Create: `lab-factory/src/labfactory/context.py`
- Test: `lab-factory/tests/test_context.py`, `lab-factory/tests/conftest.py`

**Interfaces:**
- Consumes: `is_known_unit` (Task 1).
- Produces these frozen dataclasses. Tuple fields stay tuples.
  - `Parameter(name: str, unit: str, minimum: float, maximum: float)`
  - `Command(name: str, required: tuple[str, ...], optional: tuple[str, ...] = ())`, where the entries are parameter names
  - `Instrument(id: str, name: str, model: str, firmware: str, parameters: tuple[Parameter, ...], commands: tuple[Command, ...], notes: str = "")`
  - `Document(id: str, kind: str, title: str, source: str, text: str)`
  - `Lab(id: str, name: str, instruments: tuple[Instrument, ...], documents: tuple[Document, ...])`
  - `Experiment(id: str, lab_id: str, title: str, goal: str, instrument_ids: tuple[str, ...], documents: tuple[Document, ...])`
- Also produces:
  - `class ContextError(ValueError)`
  - `lab_from_dict(d: dict) -> Lab` and `experiment_from_dict(d: dict) -> Experiment`. Both validate, and both raise `ContextError`.
  - `to_dict(record) -> dict`
  - `canonical_digest(data: dict) -> str`: lowercase hex SHA-256 of `json.dumps(data, sort_keys=True, separators=(",", ":"))`
  - `digest(record) -> str`, which is `canonical_digest(to_dict(record))`
  - `Lab.instrument(id) -> Instrument | None`
  - `Lab.document(id) -> Document | None`
  - `Instrument.parameter(name) -> Parameter | None`
  - `Instrument.command(name) -> Command | None`

- [ ] **Step 1: Write the conftest fixtures.**
  - `uvvis_lab_dict`: lab `id="emory-biophys"`, with one instrument and one document:
    - instrument `id="uvvis-1"`, `model="SP-550"`, `firmware="2.3.1"`
    - parameters: `wavelength` `nm` [400, 700], `temperature` `K` [278.15, 303.15], `integration_time` `s` [0.1, 10]
    - commands: `read_absorbance` (required `["wavelength"]`, optional `["integration_time"]`) and `set_temperature` (required `["temperature"]`)
    - document `id="sop-cuvette"`, kind `sop`
  - `b12_experiment_dict`: `id="b12-vial-a"`, `lab_id="emory-biophys"`, `instrument_ids=["uvvis-1"]`, one document `id="b12-protocol"` of kind `sop`

- [ ] **Step 2: Write the failing tests.**
  - `test_round_trip_and_digest_stable`: `to_dict(lab_from_dict(d)) == d`. `digest` matches for two separately parsed copies, and is 64 hex characters long.
  - `test_digest_changes_with_content`: changing `firmware` to `"2.3.2"` changes the digest.
  - `test_rejects_invalid_context`: each of these raises `ContextError`:
    - minimum greater than maximum
    - parameter unit `"nanometers"`
    - duplicate instrument ids
    - duplicate document ids
    - duplicate parameter or command names on one instrument
    - a command whose required or optional list names `"slit_width"`, which is not a parameter
    - document kind `"blog"`
    - experiment with `instrument_ids=[]`
    - lab missing `"name"`

- [ ] **Step 3: Run `uv run pytest tests/test_context.py -v`.** Expected: FAIL.

- [ ] **Step 4: Implement `context.py`.** The `*_from_dict` functions take JSON-shaped dicts: lists for tuples and nested objects for records. `to_dict` returns the same shape.

- [ ] **Step 5: Run the tests.** Expected: PASS.

- [ ] **Step 6: Commit** with the message `feat(lab-factory): lab and experiment context with instrument commands`.

---

### Task 3: Revisioned SQLite store

**Files:**
- Create: `lab-factory/src/labfactory/store.py`
- Modify: `lab-factory/tests/conftest.py` (add a `store` fixture built on `tmp_path`)
- Test: `lab-factory/tests/test_store.py`

**Interfaces:**
- Consumes: the Task 2 records, `digest`, `ContextError`.
- Produces:
  - `Revision(number: int, digest: str)` (frozen)
  - `class NotFound(LookupError)`
  - `Store(path: str | os.PathLike)`: opens or creates the database and applies the schema
  - `Store.put_lab(lab: Lab) -> Revision`
  - `Store.get_lab(lab_id: str, number: int | None = None) -> tuple[Lab, Revision]`
  - `Store.put_experiment(exp: Experiment) -> Revision`
  - `Store.get_experiment(experiment_id: str, number: int | None = None) -> tuple[Experiment, Revision]`
  - `Store.transaction() -> contextlib.AbstractContextManager[sqlite3.Connection]`: runs `BEGIN IMMEDIATE`, commits on success and rolls back on an exception

- [ ] **Step 1: Write the failing tests.**
  - `test_revisions_are_append_only`:
    - Put the lab, which is revision 1. Then put a version with `firmware="2.3.2"`, which is revision 2.
    - `get_lab(id)` returns revision 2.
    - `get_lab(id, 1)` still has firmware `"2.3.1"`, and its digest equals `digest()` of the original.
  - `test_identical_put_returns_existing_revision`: putting the same lab twice returns `Revision(1, …)` both times. Per the spec, re-saving identical content isn't a change.
  - `test_experiment_requires_known_lab_and_instruments`: `put_experiment` raises `ContextError` when the lab is missing, and again when an `instrument_ids` entry is absent from the lab's latest revision.
  - `test_missing_raises_not_found`: `get_lab("nope")` and `get_lab(id, 99)` raise `NotFound`.
  - `test_reopen_persists`: a new `Store` on the same path reads revision 2.

- [ ] **Step 2: Run `uv run pytest tests/test_store.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `store.py`.**
  - Table: `records(kind TEXT, id TEXT, number INTEGER, digest TEXT, body TEXT, created_at TEXT, PRIMARY KEY(kind, id, number))`. The body is canonical JSON.
  - Connect with `sqlite3.connect(path, isolation_level=None, timeout=5.0)`. The 5-second busy timeout makes a competing writer wait, so it doesn't fail with "database is locked".
  - All writes go through `transaction()`.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** with the message `feat(lab-factory): append-only revision store`.

---

### Task 4: Artifact formats and rendering

**Files:**
- Create: `lab-factory/src/labfactory/artifacts.py`
- Test: `lab-factory/tests/test_artifacts.py`

**Interfaces:**
- Produces these frozen dataclasses:
  - `Setting(parameter: str, value: float, unit: str)`
  - `RunStep(command: str, settings: tuple[Setting, ...])`
  - `RunPlan(instrument_id: str, steps: tuple[RunStep, ...])`
  - `Action(instrument_id: str, command: str, settings: tuple[Setting, ...])`
  - `Amount(what: str, value: float, unit: str)`
  - `ProcedureStep(text: str, citations: tuple[str, ...], action: Action | None = None, amounts: tuple[Amount, ...] = ())`
  - `Procedure(steps: tuple[ProcedureStep, ...])`
- Also produces:
  - `class ArtifactError(ValueError)`
  - `KINDS = ("procedure", "run_plan")`
  - `parse_artifact(kind: str, data: dict) -> RunPlan | Procedure`
  - `render_step(step: ProcedureStep) -> list[str]`
  - `render_procedure(procedure: Procedure) -> str` and `render_run_plan(plan: RunPlan) -> str`
  - `ARTIFACT_EXAMPLES: dict[str, dict]`, holding exactly the two payloads below

  Run plan:

  ```json
  {"instrument_id": "uvvis-1",
   "steps": [{"command": "read_absorbance",
              "settings": [{"parameter": "wavelength", "value": 550, "unit": "nm"}]}]}
  ```

  Procedure:

  ```json
  {"steps": [
    {"text": "Rinse the cuvette twice with buffer.", "citations": ["sop-cuvette"]},
    {"text": "Pipette the sample into the cuvette.", "citations": ["b12-protocol"],
     "amounts": [{"what": "sample", "value": 1, "unit": "mL"}]},
    {"text": "Place the cuvette in the holder and read the absorbance.", "citations": ["sop-cuvette"],
     "action": {"instrument_id": "uvvis-1", "command": "read_absorbance",
                "settings": [{"parameter": "wavelength", "value": 550, "unit": "nm"}]}}]}
  ```

  `render_step` returns these lines, in this order, and leaves out any line whose part is empty. Values retain their numeric precision (e.g. `550.0004 nm` and `550 nm`), and multiple settings or amounts are joined with `", "`.
  - `On {instrument_id}: {command} ({parameter} {value} {unit}, …)`
  - `Amounts, not checked against instrument limits: {what} {value} {unit}, …`
  - `Notes, not checked by code: {text}`
  - `Citations: {document ids in the step’s order}`

  `render_procedure` writes each step as `Step {i}` followed by its lines, each indented two spaces, with steps separated by a blank line.

- [ ] **Step 1: Write the failing tests.**
  - `test_parses_both_examples`: `parse_artifact(k, ARTIFACT_EXAMPLES[k])` succeeds for each kind in `KINDS`.
  - `test_rejects_malformed`: each of these raises `ArtifactError`:
    - kind `"analysis_app"`
    - empty `steps`
    - missing `steps`
    - a setting `value` of `"550"`
    - a setting `value` of `True`
    - an `action` without `command`
    - an amount `value` of `"1"`
    - `citations` given as a string
  - `test_render_uses_action_not_text`: render a step with text `"Measure at 800 nm."`, citations `["sop-cuvette"]` and an action at wavelength 550 nm. The lines are exactly:
    - `"On uvvis-1: read_absorbance (wavelength 550 nm)"`
    - `"Notes, not checked by code: Measure at 800 nm."`
    - `"Citations: sop-cuvette"`
  - `test_render_procedure_example`: `render_procedure` of the parsed procedure example starts with `"Step 1\n  Notes, not checked by code: Rinse the cuvette twice with buffer.\n  Citations: sop-cuvette\n\nStep 2\n"`, and contains `"  Amounts, not checked against instrument limits: sample 1 mL"`.

  Missing citations are a *check* (Task 5), not a parse error.

- [ ] **Step 2: Run `uv run pytest tests/test_artifacts.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `artifacts.py`.** Accept `int` or `float` for numeric values, and reject `bool`.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** with the message `feat(lab-factory): artifact formats with rendered instrument actions`.

---

### Task 5: Checks

**Files:**
- Create: `lab-factory/src/labfactory/checks.py`
- Test: `lab-factory/tests/test_checks.py`

**Interfaces:**
- Consumes: `convert`, `UnitError`, `is_known_unit` (Task 1); `Lab`, `Experiment`, `Instrument.parameter`, `Instrument.command` (Task 2); the artifacts (Task 4).
- Produces:
  - `CheckResult(name: str, passed: bool, detail: str)` (frozen)
  - `check_artifact(artifact: RunPlan | Procedure, lab: Lab, experiment: Experiment) -> list[CheckResult]`
  - `all_passed(results: list[CheckResult]) -> bool`: true only if the list is non-empty and every result passed
  - `find_text_quantities(text: str) -> list[str]`: the matched substrings, in order
- Result names, where `i` is the 1-based step number:
  - Instrument checks (used by every run-plan step and every procedure action):
    - `"step {i}: instrument listed"`
    - `"step {i}: command"`
    - one `"step {i}: {parameter}"` per setting

    A run plan has one instrument, so its result is named `"instrument listed"`, without a step prefix.
  - Procedure only:
    - `"step {i}: citations"`
    - `"step {i}: text values"`
    - one `"step {i}: amount {what}"` per amount
- Rules:
  - **Command.** Fails with `"unknown command {c} on {instrument_id}"`, or `"missing required setting {p}"` when one is absent.
  - **Settings.**
    - Duplicate settings for a parameter within a run step or procedure action fail with a readable detail.
    - A parameter the instrument doesn't have fails with `"unknown parameter"`.
    - A parameter the command doesn't accept fails with `"not accepted by {command}"`.
    - A unit problem fails with the `UnitError` message.
    - An out-of-range value fails with `"{v} {unit} is outside [{min}, {max}] {param_unit}"`.
    - If the instrument isn't on the experiment or in the lab, every setting fails with `"unknown instrument"`.
  - **Text values.** Fails when `find_text_quantities(step.text)` is non-empty. The detail lists the matches and says `"put instrument values in the action and hand-measured values in amounts"`.
  - **Amounts.** Fail only when the unit is unknown.
  - **Number format.** Numeric details preserve the precision of submitted values and limits and display whole numbers without a decimal suffix.

  Free-text notes still require human judgment. The checked instruction comes from the structured instrument action. `find_text_quantities` matches a number (`\d+(?:\.\d+)?`), optional whitespace, then a unit token that isn't followed by a letter. Unit tokens:
  - every supported unit spelling (case-sensitive)
  - the symbols `°C`, `µL`, `μL`, `µm`, `μm`
  - these words, case-insensitive: `nanometer(s)`, `micrometer(s)`, `microliter(s)`, `milliliter(s)`, `liter(s)`, `millisecond(s)`, `second(s)`, `sec`, `minute(s)`, `mins`, `hour(s)`, `hr(s)`, `kelvin`, `celsius`, `gauss`, `tesla`, `millitesla`

- [ ] **Step 1: Write the failing tests.** Use the conftest lab and experiment.
  - `test_valid_examples_pass`: `all_passed` is true for both `ARTIFACT_EXAMPLES`.
  - `test_limits_are_inclusive`: 400 nm and 700 nm pass. 399.9 nm fails, with `"outside [400, 700] nm"` in the detail.
  - `test_celsius_setting_against_kelvin_limit`: a `set_temperature` step at 30 `degC` passes, and at 31 `degC` fails.
  - `test_unit_converts_before_comparing`: an `integration_time` setting on `read_absorbance` passes at 500 `ms` and fails at 11000 `ms`.
  - `test_unknown_unit_and_parameter_fail_closed`: none of these raises.
    - setting `wavelenght` fails with `"unknown parameter"`
    - unit `"nanometers"` fails with `"unknown unit"`
    - unit `"mL"` on `wavelength` fails with `"dimension"`
  - Reject two settings for the same parameter in one run step or procedure action.
  - `test_commands_must_exist_and_be_complete`:
    - command `read_absorbence` fails `"step 1: command"` with `"unknown command read_absorbence on uvvis-1"`.
    - `read_absorbance` with only `integration_time` fails with `"missing required setting wavelength"`.
    - `read_absorbance` with a `temperature` setting fails `"step 1: temperature"` with `"not accepted by read_absorbance"`.
  - `test_instrument_not_in_experiment_fails`: `instrument_id="epr-1"` fails `"instrument listed"`, and each setting fails with `"unknown instrument"`.
  - `test_procedure_citations`:
    - `citations=[]` fails `"step 1: citations"` with `"no citation"`.
    - `"sop-missing"` fails with `"unknown document sop-missing"`.
    - `"sop-cuvette"` (lab) and `"b12-protocol"` (experiment) pass.
  - `test_values_in_text_fail`:
    - text `"Measure at 800 nm."` with no action fails `"step 1: text values"` with `"800 nm"` in the detail.
    - the same text with an action at 550 nm also fails `"step 1: text values"`, while `"step 1: wavelength"` passes.
    - `"Incubate for 5 minutes."` and `"Pipette 1 mL of sample."` fail.
    - `"Rinse the cuvette twice."` and `"Repeat 3 times."` pass.
  - `test_find_text_quantities`:
    - `find_text_quantities("Heat to 25 °C, then read at 550nm for 2 s")` returns `["25 °C", "550nm", "2 s"]`.
    - `find_text_quantities("2 steps")` returns `[]`.
  - `test_amount_units_fail_closed`: an amount in unit `"cups"` fails `"step 1: amount sample"`.

- [ ] **Step 2: Run `uv run pytest tests/test_checks.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `checks.py`.** Run-plan steps and procedure actions share one private helper for the instrument, command and setting checks.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** with the message `feat(lab-factory): command, limit, citation and text-value checks`.

---

### Task 6: Work orders

**Files:**
- Create: `lab-factory/src/labfactory/workorders.py`
- Modify: `lab-factory/src/labfactory/store.py` (add the work-order tables to the schema)
- Test: `lab-factory/tests/test_workorders.py`

**Interfaces:**
- Consumes:
  - from Task 2: `canonical_digest`
  - from Task 3: `Store`, `Store.transaction`, `NotFound`
  - from Task 4: `parse_artifact`, `ArtifactError`, `KINDS`
  - from Task 5: `check_artifact`, `all_passed`, `CheckResult`
- Produces:
  - `WorkOrder(id: str, experiment_id: str, experiment_revision: int, lab_id: str, lab_revision: int, kind: str, objective: str, status: str, worker: str | None, released_submission: int | None)` (frozen)
  - `Submission(work_order_id: str, number: int, worker: str, artifact: dict, artifact_digest: str, results: tuple[CheckResult, ...], passed: bool, submitted_at: str)` (frozen). `artifact_digest` is `canonical_digest(artifact)`.
  - `class WorkOrderError(RuntimeError)`
  - `WorkOrders(store: Store)`, with these methods:
    - `create(experiment_id: str, kind: str, objective: str) -> WorkOrder`: ids are `"WO-1"`, `"WO-2"`, and so on, and the order pins the current revisions
    - `get(id: str) -> WorkOrder`
    - `list(status: str | None = None) -> list[WorkOrder]`
    - `claim(id: str, worker: str) -> WorkOrder`
    - `submit(id: str, worker: str, artifact: dict) -> Submission`
    - `approve(id: str, person: str, submission: int) -> WorkOrder`
    - `reject(id: str, person: str, submission: int, reason: str) -> WorkOrder`
    - `submissions(id: str) -> list[Submission]`
    - `latest_rejection(id: str) -> dict | None`, with the keys `submission`, `by`, `reason` and `artifact`
    - `history(id: str) -> list[dict]`. Each entry has the keys `event`, `actor`, `at`, `submission` and `note`. `event` is one of `created`, `claimed`, `submitted`, `approved`, `rejected`.
    - `pinned_context(id: str) -> tuple[Lab, Experiment]`

  Transitions:
  - `claim`: `open` → `in_progress`
  - `submit`, all checks passed: `in_progress` → `in_review`
  - `submit`, a check failed: stays `in_progress`, and the submission is recorded
  - `approve`: `in_review` → `released`, and `released_submission` is set
  - `reject`: `in_review` → `open`, and `worker` is cleared
  - `approve` and `reject` raise `WorkOrderError` unless the named submission is the latest one. The message is `"submission {n} is not the latest (latest is {m})"`.
  - Any other call raises `WorkOrderError`, and so does `create` with an unknown kind.
  - If `parse_artifact` raises `ArtifactError`, `submit` lets it propagate and records nothing.

- [ ] **Step 1: Write the failing tests.**
  - `test_create_pins_current_revisions`: the order has `lab_revision == 1`, `experiment_revision == 1`, `status == "open"` and `released_submission is None`.
  - `test_happy_path_to_release`:
    - Claim by `"codex"`, then submit the run-plan example. The order is `in_review`.
    - Run `approve(id, "Neal", 1)`. The order is `released` with `released_submission == 1`.
    - `history` events are `["created", "claimed", "submitted", "approved"]`.
    - The approve entry has `actor == "Neal"`, `submission == 1`, and the submission's `artifact_digest` in its `note`.
  - `test_failed_checks_stay_in_progress`: submitting 800 nm leaves the order `in_progress`, with `passed` false on submission 1. Resubmitting at 550 nm creates submission 2 and moves the order to `in_review`.
  - `test_submit_requires_claiming_worker_and_in_progress`: each of these raises `WorkOrderError`, and the number of submissions stays the same:
    - submit by `"claude"` after `"codex"` claimed
    - submit to an `open` order
    - submit to a `released` order
  - `test_approval_names_reviewed_submission`:
    - Submission 1 passes, and `reject(id, "Neal", 1, "use 2x dilution")` reopens the order.
    - `"claude"` claims it and submits submission 2, which passes.
    - `approve(id, "Neal", 1)` raises `"submission 1 is not the latest (latest is 2)"`, and the order stays `in_review`.
    - `approve(id, "Neal", 2)` releases it, with `released_submission == 2`.
  - `test_reject_and_handoff`:
    - `approve` on an `in_progress` order raises.
    - After a rejection, the order is `open` with `worker is None`.
    - `latest_rejection` returns `{"submission": 1, "by": "Neal", "reason": "use 2x dilution", "artifact": <submitted dict>}`.
  - `test_checks_use_pinned_lab_revision`:
    - Create the order, then `put_lab` a revision 2 that widens `wavelength` to [400, 900].
    - Submitting 800 nm to the old order still fails.
    - A new order created afterwards passes with 800 nm.
  - `test_only_one_claim_wins_across_connections`:
    - Two threads each open their own `Store` on the same file, wait on a shared `threading.Barrier(2)`, then call `claim` with workers `"codex"` and `"claude"`.
    - Exactly one claim returns a `WorkOrder`, and the other raises `WorkOrderError`. Neither raises `sqlite3.OperationalError`.
    - `history` contains exactly one `claimed` event, and its actor is the winner.

- [ ] **Step 2: Run `uv run pytest tests/test_workorders.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `workorders.py` and the schema.**
  - Tables: `work_orders`, `submissions`, `events`.
  - Each transition is one `transaction()`: read the order and its latest submission, validate, then run a conditional `UPDATE … WHERE id = ? AND status = ?`. If that changes 0 rows, raise `WorkOrderError` with the current status in the message.
  - Checks load the pinned revisions with `get_lab(lab_id, lab_revision)` and `get_experiment(experiment_id, experiment_revision)`.

- [ ] **Step 4: Run the full suite with `uv run pytest -v`.** Expected: PASS.

- [ ] **Step 5: Commit** with the message `feat(lab-factory): work orders with pinned context and submission-specific release`.

---

### Task 7: Agent tools and MCP server

**Files:**
- Create: `lab-factory/src/labfactory/agent.py`, `lab-factory/src/labfactory/mcp_server.py`
- Test: `lab-factory/tests/test_agent.py`

**Interfaces:**
- Consumes: `WorkOrders` and its errors (Task 6); `ArtifactError`, `ARTIFACT_EXAMPLES` (Task 4); `to_dict` (Task 2).
- Produces `AgentTools(store: Store)`. Every method returns JSON-serialisable values. Instead of raising `WorkOrderError`, `ArtifactError` or `NotFound`, it returns `{"error": "<message>"}`.
  - `list_work_orders(status: str = "open") -> list[dict] | dict`
  - `get_work_order_context(work_order_id: str) -> dict`, with these keys:
    - `work_order`
    - `lab` (pinned)
    - `experiment` (pinned)
    - `artifact_example`
    - `instructions`
    - `previous_rejection` (the value of `latest_rejection`, or `None`)
  - `claim_work_order(work_order_id: str, worker: str) -> dict`
  - `submit_artifact(work_order_id: str, worker: str, artifact: dict) -> dict`, with the keys `status`, `passed`, `results` (a list of `{name, passed, detail}`), `submission` and `artifact_digest`
- Also produces `build_server(db_path: str) -> FastMCP`. It registers exactly these four tools, under the same names, as thin wrappers.

- [ ] **Step 1: Write the failing tests.**
  - `test_agent_flow_returns_plain_dicts`:
    - list → context. The context has the six keys, `previous_rejection is None`, and `lab["instruments"][0]["commands"][0]["name"] == "read_absorbance"`.
    - claim → submit the valid plan. The result is `{"status": "in_review", "passed": True, …}`.
    - `json.dumps` succeeds on every return value.
  - `test_errors_are_returned_not_raised`: each of these returns a dict with an `"error"` key:
    - an unknown id
    - a malformed artifact
    - a submit without a claim
  - `test_rejected_work_reaches_next_agent`:
    - `"codex"` submits, and `WorkOrders.reject(id, "Neal", 1, "use 2x dilution")` reopens the order.
    - `"claude"` claims it through `AgentTools`.
    - `get_work_order_context` returns `previous_rejection["reason"] == "use 2x dilution"`, and `previous_rejection["artifact"]` equals what `"codex"` submitted.
  - `test_server_exposes_no_approval`: `{t.name for t in asyncio.run(build_server(str(db)).list_tools())} == {"list_work_orders", "get_work_order_context", "claim_work_order", "submit_artifact"}`.

- [ ] **Step 2: Run `uv run pytest tests/test_agent.py -v`.** Expected: FAIL.

- [ ] **Step 3: Implement `agent.py` and `mcp_server.py`.** Set `instructions` to exactly:

  > "Build the artifact from the pinned lab and experiment context only. Use only commands the instrument lists, with every required setting, each in a supported unit and within its limits. In procedures, put instrument values in the step's action and hand-measured values in amounts; never write numbers with units in the text. Every procedure step must cite a document id from the lab or experiment. If previous_rejection is present, address its reason. Submit; if checks fail, read each failing result, fix the artifact, and resubmit. A person reviews and releases passing work."

- [ ] **Step 4: Run the full suite.** Expected: PASS.

- [ ] **Step 5: Commit** with the message `feat(lab-factory): agent tools and MCP server without release rights`.

---

### Task 8: CLI, examples, MCP round trip and README

**Files:**
- Create:
  - `lab-factory/src/labfactory/cli.py`
  - `lab-factory/src/labfactory/__main__.py` (calls `raise SystemExit(main())`)
  - `lab-factory/examples/uvvis-lab.json`
  - `lab-factory/examples/b12-experiment.json`
  - `lab-factory/README.md`
- Modify: `lab-factory/tests/conftest.py` (load the fixtures from the example files)
- Test: `lab-factory/tests/test_cli.py`, `lab-factory/tests/test_mcp_stdio.py`

**Interfaces:**
- Consumes: `Store`, `WorkOrders`, `lab_from_dict`, `experiment_from_dict`, `parse_artifact`, `render_procedure` and `build_server`.
- Produces `main(argv: list[str] | None = None) -> int`. The global option `--db PATH` defaults to `labfactory.db`. Commands:
  - `lab put FILE`, which prints `{lab_id} revision {n}`
  - `experiment put FILE`
  - `wo create EXPERIMENT_ID --kind {procedure,run_plan} --objective TEXT`, which prints the id
  - `wo list [--status S]`
  - `wo show ID`, which prints these lines:
    - `{id} {kind} {status}`
    - `experiment {experiment_id} revision {n} · lab {lab_id} revision {m}`
    - for each submission, `submission {n} by {worker} · digest {first 12 hex} · passed|failed`, followed by one `  pass|FAIL  {name}: {detail}` line per result, and then the submitted artifact: render a run plan’s instrument, commands and every parameter, value and unit in execution order, or render each procedure step with its citations, action, amounts and notes
    - `awaiting review: submission {n}` while the order is `in_review`
    - `released: submission {n} by {person}` once it is released
    - the history
  - `wo approve ID --submission N --by NAME`
  - `wo reject ID --submission N --by NAME --reason TEXT`
  - `serve`, which runs MCP over stdio

  Success returns 0. A `ContextError`, `NotFound`, `WorkOrderError`, `OSError` or `json.JSONDecodeError` prints `error: <message>` to stderr and returns 1.

- [ ] **Step 1: Write the example files.** They hold the Task 2 fixture content, and conftest now loads them, so the two can't drift apart.

- [ ] **Step 2: Write the failing tests.**
  - `test_end_to_end`:
    - Through `main`, run `lab put`, `experiment put` and `wo create … --kind run_plan`. It prints `WO-1`.
    - Through `AgentTools`, claim and submit the run-plan example.
    - `main([... "wo", "approve", "WO-1", "--submission", "1", "--by", "Neal"])` returns 0.
    - The `wo show WO-1` output contains `"released: submission 1 by Neal"` and `"lab emory-biophys revision 1"`.
  - `test_show_renders_procedure`: for a procedure order with a submitted example, `wo show` contains `"On uvvis-1: read_absorbance (wavelength 550 nm)"` and `"awaiting review: submission 1"`.
  - Verify `wo show` before approval preserves multi-step and multi-setting order, exact numeric precision and per-step citations.
  - `test_cli_errors_exit_1`: each returns 1 with stderr starting with `error:`:
    - approving an `open` order
    - approving a stale submission number
    - a nonexistent file
  - `test_mcp_stdio_round_trip` (in `test_mcp_stdio.py`):
    - Set up the lab, the experiment and WO-1 through `main`.
    - Start `sys.executable -m labfactory --db <db> serve` with `mcp.client.stdio.stdio_client` and `StdioServerParameters`, then open a `ClientSession` and call `initialize()`.
    - Call `claim_work_order` as `"codex"` and `submit_artifact` with the run-plan example. Parse `json.loads(result.content[0].text)`, which shows `status == "in_review"`.
    - Reject submission 1 through `main`.
    - In a second session, `"claude"` claims the order, and `get_work_order_context` returns `previous_rejection["reason"] == "use 2x dilution"`.
    - Drive it with `asyncio.run` inside the test.

- [ ] **Step 3: Implement `cli.py` and `__main__.py`.**

- [ ] **Step 4: Run the full suite with `uv run pytest -v`.** Expected: all tests PASS.

- [ ] **Step 5: Write `README.md`.** It covers:
  - what the core does, in three sentences
  - the quickstart, using the example files
  - how to connect agents:
    - Claude Code: `claude mcp add labfactory -- uv run --project <abs path>/lab-factory labfactory --db <abs path>/labfactory.db serve`
    - Codex: the equivalent `[mcp_servers.labfactory]` entry in `~/.codex/config.toml`
  - what a release certifies, copied from the spec section of that name
  - this trust statement, verbatim:

  > **Trust assumption.** Agents connected over MCP cannot approve or release work; only `labfactory wo approve` does, and it names the exact submission a person reviewed. The core does not stop an agent that has shell access as your computer user from running that command itself. If that matters for your lab, don't give coding agents a shell on the machine that holds the database. Enforced human-only release comes with the hosted lab deployment.

- [ ] **Step 6: Run a manual smoke check.** Run `uv run labfactory --db "$(mktemp -d)/lf.db" lab put examples/uvvis-lab.json`. Expected output: `emory-biophys revision 1`.

- [ ] **Step 7: Commit** with the message `feat(lab-factory): CLI, MCP round trip and README with trust statement`.
