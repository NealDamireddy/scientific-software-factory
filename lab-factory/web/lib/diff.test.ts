import assert from "node:assert/strict";
import { test } from "node:test";

import { diffSteps } from "./diff.ts";
import type { ProcedureStep, RunStep } from "./types.ts";

const procedure: ProcedureStep[] = [
  { text: "Rinse the cuvette.", citations: ["sop-cuvette"] },
  { text: "Fill the cuvette from vial A.", citations: ["b12-protocol"], amounts: [{ what: "solution", value: 3, unit: "mL" }] },
  { text: "Set the temperature.", citations: [],
    action: { instrument_id: "uvvis-1", command: "set_temperature", settings: [{ parameter: "temperature", value: 298.15, unit: "K" }] } },
  { text: "Read the absorbance.", citations: ["b12-protocol"],
    action: { instrument_id: "uvvis-1", command: "read_absorbance", settings: [{ parameter: "wavelength", value: 550, unit: "nm" }] } },
  { text: "Record the reading.", citations: [] },
];

function copy<T>(value: T): T {
  return structuredClone(value);
}

test("an identical list is all same", () => {
  assert.deepEqual(diffSteps(procedure, copy(procedure)), procedure.map((_, i) => ({ change: "same", before: i, after: i })));
});

test("a changed step-4 citation is reported as changed", () => {
  const after = copy(procedure);
  after[3].citations = ["sop-cuvette"];
  const changes = diffSteps(procedure, after);
  assert.deepEqual(changes[3], { change: "changed", before: 3, after: 3, fields: ["citations"] });
  assert.deepEqual(changes.filter((c) => c.change !== "same").length, 1);
});

test("an inserted step is added", () => {
  const after = copy(procedure);
  after.splice(2, 0, { text: "Wipe the optical faces.", citations: ["sop-cuvette"] });
  assert.deepEqual(diffSteps(procedure, after), [
    { change: "same", before: 0, after: 0 },
    { change: "same", before: 1, after: 1 },
    { change: "added", after: 2 },
    { change: "same", before: 2, after: 3 },
    { change: "same", before: 3, after: 4 },
    { change: "same", before: 4, after: 5 },
  ]);
});

test("a deleted step is removed, placed where it occurred", () => {
  const after = copy(procedure);
  after.splice(1, 1);
  assert.deepEqual(diffSteps(procedure, after), [
    { change: "same", before: 0, after: 0 },
    { change: "removed", before: 1 },
    { change: "same", before: 1 + 1, after: 1 },
    { change: "same", before: 3, after: 2 },
    { change: "same", before: 4, after: 3 },
  ]);
});

test("a reworded step is a removal followed by an addition", () => {
  const after = copy(procedure);
  after[4] = { text: "Write the reading in the notebook.", citations: [] };
  assert.deepEqual(diffSteps(procedure, after).slice(4), [
    { change: "removed", before: 4 },
    { change: "added", after: 4 },
  ]);
});

test("several changed fields are listed in a fixed order", () => {
  const after = copy(procedure);
  after[1] = { text: after[1].text, citations: [], action: { instrument_id: "uvvis-1", command: "read_absorbance", settings: [] } };
  assert.deepEqual(diffSteps(procedure, after)[1],
    { change: "changed", before: 1, after: 1, fields: ["citations", "action", "amounts"] });
});

test("a run-step settings change is reported as changed", () => {
  const before: RunStep[] = [
    { command: "set_temperature", settings: [{ parameter: "temperature", value: 298.15, unit: "K" }] },
    { command: "read_absorbance", settings: [{ parameter: "wavelength", value: 550, unit: "nm" }] },
  ];
  const after = copy(before);
  after[1].settings[0].value = 595;
  assert.deepEqual(diffSteps(before, after), [
    { change: "same", before: 0, after: 0 },
    { change: "changed", before: 1, after: 1, fields: ["settings"] },
  ]);
});

test("empty lists and whole-list additions and removals", () => {
  assert.deepEqual(diffSteps([], []), []);
  assert.deepEqual(diffSteps([], procedure.slice(0, 2)), [{ change: "added", after: 0 }, { change: "added", after: 1 }]);
  assert.deepEqual(diffSteps(procedure.slice(0, 2), []), [{ change: "removed", before: 0 }, { change: "removed", before: 1 }]);
});
