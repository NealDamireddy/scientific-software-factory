import assert from "node:assert/strict";
import { test } from "node:test";

import { ClientError } from "../types.ts";
import type { CheckResult, ProcedureStep, RunPlan } from "../types.ts";
import { procedureTemplate, procedureViews, runPlanViews, sampleLab } from "./content.ts";

const instruments = sampleLab().instruments;

test("an un-prefixed failing result lands on step 1 of a run plan view", () => {
  const plan: RunPlan = {
    instrument_id: "ghost",
    steps: [{ command: "read_absorbance", settings: [] }, { command: "read_absorbance", settings: [] }],
  };
  const results: CheckResult[] = [
    { name: "instrument listed", passed: false, detail: "unknown instrument ghost in the pinned lab or experiment" },
    { name: "step 2: command", passed: false, detail: "x" },
    { name: "step 1: command", passed: true, detail: "ok" },
  ];
  const views = runPlanViews(plan, results, instruments);
  assert.deepEqual(views[0].failures.map((f) => f.name), ["instrument listed"]);
  assert.deepEqual(views[1].failures.map((f) => f.name), ["step 2: command"]);
});

test("an un-prefixed failing result lands on step 1 of a procedure view", () => {
  const steps: ProcedureStep[] = [
    { text: "One.", citations: ["sop-cuvette"] },
    { text: "Two.", citations: ["sop-cuvette"] },
  ];
  const results: CheckResult[] = [
    { name: "instrument listed", passed: false, detail: "nope" },
    { name: "instrument listed", passed: true, detail: "fine" },
  ];
  const views = procedureViews(steps, results, sampleLab().documents, instruments);
  assert.deepEqual(views[0].failures, [{ name: "instrument listed", passed: false, detail: "nope" }]);
  assert.deepEqual(views[1].failures, []);
});

test("procedureTemplate with no citations is invalid", () => {
  assert.throws(
    () => procedureTemplate(instruments[0], []),
    (error) => error instanceof ClientError && error.code === "invalid"
      && error.message === "A procedure needs at least one document to cite.",
  );
});
