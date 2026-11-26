import assert from "node:assert/strict";
import { test } from "node:test";

import { artifactSteps, procedureSteps, runPlanSteps } from "./artifact.ts";

const action = { instrument_id: "uvvis-1", command: "read_absorbance", settings: [{ parameter: "wavelength", value: 595, unit: "nm" }] };

test("procedureSteps reads well-formed steps with their optional fields", () => {
  const artifact = {
    steps: [
      { text: "Rinse the cuvette.", citations: ["sop"] },
      { text: "Read it.", citations: [], action, amounts: [{ what: "dye", value: 1, unit: "mL" }] },
    ],
  };
  assert.deepEqual(procedureSteps(artifact), artifact.steps);
  assert.deepEqual(artifactSteps("procedure", artifact), artifact.steps);
});

test("procedureSteps returns a copy, never the artifact's own arrays", () => {
  const artifact = { steps: [{ text: "Rinse.", citations: ["sop"] }] };
  const steps = procedureSteps(artifact);
  assert.ok(steps);
  steps[0].citations.push("other");
  assert.deepEqual(artifact.steps[0].citations, ["sop"]);
});

test("procedureSteps reads an empty step list as no steps", () => {
  assert.deepEqual(procedureSteps({ steps: [] }), []);
  assert.deepEqual(runPlanSteps({ instrument_id: "uvvis-1", steps: [] }), []);
});

test("procedureSteps returns null for anything malformed, never a half-read or empty list", () => {
  for (const artifact of [
    undefined, null, 3, "steps", [], {}, { steps: "x" }, { steps: [null] },
    { steps: [{ text: 1, citations: [] }] },
    { steps: [{ text: "a" }] },
    { steps: [{ text: "a", citations: [2] }] },
    { steps: [{ text: "a", citations: [], action: { command: "x", settings: [] } }] },
    { steps: [{ text: "a", citations: [], action: { ...action, settings: [{ parameter: "w", value: "595", unit: "nm" }] } }] },
    { steps: [{ text: "a", citations: [], amounts: {} }] },
    { steps: [{ text: "a", citations: [], amounts: [{ what: "dye", value: Number.NaN, unit: "mL" }] }] },
    { steps: [{ text: "ok", citations: [] }, { text: "bad" }] },
  ]) {
    assert.equal(procedureSteps(artifact), null, JSON.stringify(artifact));
  }
});

test("runPlanSteps reads a run plan and refuses malformed ones", () => {
  const plan = { instrument_id: "uvvis-1", steps: [{ command: "read_absorbance", settings: action.settings }] };
  assert.deepEqual(runPlanSteps(plan), plan.steps);
  assert.deepEqual(artifactSteps("run_plan", plan), plan.steps);
  for (const artifact of [
    null, { steps: plan.steps }, { instrument_id: "uvvis-1" }, { instrument_id: "uvvis-1", steps: [{ command: "x" }] },
    { instrument_id: "uvvis-1", steps: [{ settings: [] }] },
    { instrument_id: 1, steps: plan.steps }, { instrument_id: "uvvis-1", steps: {} },
  ]) {
    assert.equal(runPlanSteps(artifact), null, JSON.stringify(artifact));
  }
});

test("a procedure artifact read as a run plan is malformed, and the reverse", () => {
  assert.equal(runPlanSteps({ steps: [{ text: "a", citations: [] }] }), null);
  assert.equal(procedureSteps({ instrument_id: "uvvis-1", steps: [{ command: "x", settings: [] }] }), null);
  assert.equal(artifactSteps("procedure", "broken"), null);
});
