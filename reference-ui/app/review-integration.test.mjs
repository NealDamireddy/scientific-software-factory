import test from "node:test";
import assert from "node:assert/strict";
import {
  advance,
  cancel,
  createDraft,
  reviewInput,
  startRun,
} from "./simulation.ts";
import { researchSkills } from "./review-skills/catalog.ts";

const context = {
  schemaVersion: 1,
  simulationOnly: true,
  executionAuthority: "none",
  harness: null,
  connectors: [],
  skills: researchSkills.map(({ id, name, whenToUse, instructions }) => ({
    id,
    source: "builtin",
    name,
    whenToUse,
    instructions,
  })),
};
const ids = (run) => run.agentChecks.map((c) => c.skillId);
const stageIds = (stage) =>
  researchSkills.filter((s) => s.stage === stage).map((s) => s.id);
function finish(e) {
  while (e.status === "Running") e = advance(e);
  return e;
}

test("evaluates enabled scientific reviewers at the appropriate run boundary exactly once", () => {
  let experiment = startRun(
    createDraft("Measure vitamin B12", "B12 quantification"),
    "original",
    context,
  );
  assert.deepEqual(ids(experiment.runs[0]), stageIds("start"));
  const originalStart = structuredClone(experiment.runs[0].agentChecks);
  experiment = advance(experiment);
  assert.deepEqual(experiment.runs[0].agentChecks, originalStart);
  assert.deepEqual(cancel(experiment).runs[0].agentChecks, originalStart);
  experiment = finish(experiment);
  assert.deepEqual(ids(experiment.runs[0]), [
    ...stageIds("start"),
    ...stageIds("result"),
  ]);
  assert.equal(experiment.status, "Awaiting approval");
  const original = structuredClone(experiment.runs[0]);
  experiment = startRun(experiment, "repeat", context);
  assert.deepEqual(ids(experiment.runs[1]), stageIds("start"));
  assert.deepEqual(experiment.runs[1].approval, {
    originalRunNumber: 1,
    dilutionFactor: 2,
  });
  experiment = finish(experiment);
  assert.deepEqual(experiment.runs[0], original);
  assert.deepEqual(ids(experiment.runs[1]), [
    ...stageIds("start"),
    ...stageIds("result"),
    ...stageIds("repeat"),
  ]);
  for (const run of experiment.runs)
    for (const check of run.agentChecks) {
      assert.ok(["clear", "finding", "unassessed"].includes(check.verdict));
      assert.ok(check.references.length);
    }
  assert.equal(
    experiment.runs[1].agentChecks.find(
      (c) => c.skillId === "repeat-comparison",
    ).verdict,
    "clear",
  );
  assert.deepEqual(advance(experiment), experiment);
});

test("uses the recorded instrument, withholding decision, approval and original link for provider input", () => {
  const e = finish(
    startRun(createDraft("B12", "Illustrations"), "original", context),
  );
  const original = reviewInput(e, e.runs[0]);
  assert.equal(original.instrument, "UV–Vis spectrometer");
  assert.equal(original.readings.length, 6);
  assert.equal(original.sampleAU, 1.25);
  assert.equal(original.reportedConcentration, null);
  assert.equal(original.approvedDilutionFactor, undefined);
  const repeat = finish(startRun(e, "repeat", context));
  const input = reviewInput(repeat, repeat.runs[1]);
  assert.equal(input.reportedConcentration, 15);
  assert.deepEqual(input.original, {
    runNumber: 1,
    outcome: "flagged",
    sampleAU: 1.25,
  });
  const historical = { ...repeat.runs[1], approval: undefined };
  const legacy = reviewInput(repeat, historical);
  assert.equal(legacy.original, undefined);
  assert.equal(legacy.approvedDilutionFactor, undefined);
});

test("disabled, inapplicable, and instruction-only skills do not create findings", () => {
  const custom = {
    id: "research-note",
    name: "Research note",
    instructions: "Record a note",
    whenToUse: "Always",
  };
  const config = {
    ...context,
    skills: [
      ...context.skills.filter((s) =>
        ["repeat-comparison", "method-adherence"].includes(s.id),
      ),
      custom,
    ],
  };
  const exp = finish(
    startRun(
      createDraft("Time course", "Coomassie reduction"),
      "original",
      config,
    ),
  );
  assert.deepEqual(exp.runs[0].agentChecks, []);
  assert.ok(exp.runs[0].agentContext.skills.some((s) => s.id === custom.id));
});

test("method comparison reads the approved original run, including after cancellation or replay", () => {
  const config = {
    ...context,
    skills: [
      {
        id: "method",
        source: "builtin",
        name: "Method comparison",
        instructions: "Compare method records.",
        whenToUse: "After repeat",
      },
    ],
  };
  let e = cancel(
    startRun(createDraft("Measure B12", "Study"), "original", config),
  );
  e = finish(startRun(e, "original", config));
  e = finish(startRun(e, "repeat", config));
  assert.equal(e.runs[2].approval.originalRunNumber, 2);
  let check = e.runs[2].agentChecks.find((c) => c.skillId === "method");
  assert.equal(check.verdict, "clear");
  assert.ok(check.references.some((r) => r.includes("Run 2")));
  assert.ok(check.references.some((r) => r.includes("Run 3")));
  e = finish(startRun(e, "original", config));
  const lastOriginal = e.runs.at(-1);
  lastOriginal.agentContext.briefing.method.revision = "0.9";
  const altered = finish(startRun(e, "repeat", config));
  assert.equal(altered.runs.at(-1).approval.originalRunNumber, 4);
  check = altered.runs.at(-1).agentChecks.find((c) => c.skillId === "method");
  assert.equal(check.verdict, "finding");
  assert.ok(check.references.some((r) => r.includes("v0.9")));
  delete lastOriginal.agentContext;
  const missing = finish(startRun(e, "repeat", config));
  assert.equal(
    missing.runs.at(-1).agentChecks.find((c) => c.skillId === "method").verdict,
    "unassessed",
  );
  const inconsistent = { ...e, runs: e.runs.slice(0, 3) };
  assert.equal(startRun(inconsistent, "repeat", config), inconsistent);
});

test("historical custom IDs cannot invoke new scientific providers", () => {
  const config = {
    ...context,
    skills: context.skills.map(({ source, ...custom }) => custom),
  };
  const e = finish(startRun(createDraft("B12", "Study"), "original", config));
  assert.equal(e.runs[0].agentChecks.length, 0);
});
