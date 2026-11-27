import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { canonicalDigest } from "../digest.ts";
import { SAMPLE_READINGS, toCsv } from "../readings.ts";
import type { Document, ProcedureStep, RunPlan, Submission } from "../types.ts";
import { ANALYSIS_CODE, SIMULATION_CODE } from "./code.ts";
import {
  procedureResults, procedureTemplate, runPlanResults, runPlanTemplate, REFERENCE_CASES,
} from "./content.ts";
import { createSeed } from "./seed.ts";

const NOW = new Date("2026-11-26T12:00:00.000Z");
const examples = join(import.meta.dirname, "..", "..", "..", "examples");
const readJson = (name: string): unknown => JSON.parse(readFileSync(join(examples, name), "utf8"));
const TEXT_VALUE = /\d+(\.\d+)?\s*(nm|mL|uL|s|min|h|K|degC|°C)\b/;

function withoutProject<T extends { project_id?: string }>(e: T): Omit<T, "project_id"> {
  const { project_id: _drop, ...rest } = e;
  return rest;
}

test("the lab and b12-vial-a equal the example files", async () => {
  const s = await createSeed(NOW);
  assert.deepEqual(s.lab, readJson("uvvis-lab.json"));
  const b12 = s.experiments.find((e) => e.id === "b12-vial-a");
  assert.equal(b12?.project_id, "b12-quantification");
  assert.deepEqual(withoutProject(b12!), readJson("b12-experiment.json"));
  assert.deepEqual(s.settings, { sign_off: { mode: "anyone" } });
});

test("revision-1 digests match Task 2 and the records", async () => {
  const s = await createSeed(NOW);
  assert.equal(s.revisions["lab:emory-biophys"][0].digest, "dff378a22a9c72069050e3d338702ddd944987fdde5e067e6290bbc7f468b727");
  assert.equal(s.revisions["experiment:b12-vial-a"][0].digest, "84fa43772c6c04a0b658d7426a1886b19ba3696002da20758d6acb2abbe3afeb");
  for (const p of s.projects) assert.equal(s.revisions[`project:${p.id}`][0].digest, await canonicalDigest(p));
  for (const e of s.experiments) assert.equal(s.revisions[`experiment:${e.id}`][0].digest, await canonicalDigest(withoutProject(e)));
  for (const k of Object.keys(s.revisions)) {
    assert.equal(s.revisions[k].length, 1);
    assert.equal(s.revisions[k][0].number, 1);
    assert.equal(s.revisions[k][0].note, "Created");
  }
  assert.deepEqual(Object.keys(s.revisions).sort(), [
    "experiment:b12-vial-a", "experiment:coomassie-run-1", "lab:emory-biophys",
    "project:b12-quantification", "project:coomassie-reduction",
    "skill:plot-style", "skill:procedure-style", "skill:reporting-units",
  ]);
  for (const sk of s.skills) {
    const { enabled: _e, revision: _r, ...rest } = sk;
    assert.equal(s.revisions[`skill:${sk.id}`][0].digest, await canonicalDigest(rest));
    assert.equal(sk.revision, 1);
  }
});

test("projects, experiments and orders have the planned ids and statuses", async () => {
  const s = await createSeed(NOW);
  assert.deepEqual(s.projects.map((p) => p.id), ["coomassie-reduction", "b12-quantification"]);
  assert.equal(s.projects[0].documents[0].id, "coomassie-dye-prep");
  assert.equal(s.projects[0].documents[0].title, "Dye stock preparation");
  assert.deepEqual(s.projects[1].documents, []);
  assert.equal(s.projects[0].goals, "Follow the reduction of Coomassie blue's central carbon by the loss of its blue absorbance.");
  assert.equal(s.projects[1].goals, "Measure vitamin B12 in reference solutions.");
  assert.equal(s.projects[0].documents[0].kind, "note");
  assert.equal(s.projects[0].documents[0].text, "Dissolve the dye in the buffer named in the lab notebook and filter before use.");
  const run1 = s.experiments[0];
  assert.equal(run1.title, "Reducing Coomassie blue");
  assert.equal(run1.goal, "Reduce the central carbon of Coomassie blue and follow it on the spectrophotometer.");
  assert.deepEqual(run1.instrument_ids, ["uvvis-1"]);
  assert.deepEqual(run1.documents, []);
  assert.deepEqual(s.experiments.map((e) => e.id), ["coomassie-run-1", "b12-vial-a"]);
  const orders = Object.fromEntries(s.orders.map((o) => [o.id, o]));
  assert.deepEqual(Object.keys(orders), ["WO-1", "WO-B12", "WO-B12-RP"]);
  assert.deepEqual([orders["WO-1"].kind, orders["WO-1"].status, orders["WO-1"].experiment_id], ["procedure", "in_progress", "coomassie-run-1"]);
  assert.deepEqual([orders["WO-B12"].kind, orders["WO-B12"].status, orders["WO-B12"].experiment_id], ["procedure", "in_review", "b12-vial-a"]);
  assert.deepEqual([orders["WO-B12-RP"].kind, orders["WO-B12-RP"].status], ["run_plan", "in_progress"]);
  for (const o of s.orders) assert.equal(o.released_submission, null);
});

test("pins cover lab, project, experiment and each enabled skill", async () => {
  const s = await createSeed(NOW);
  const wo1 = s.orders.find((o) => o.id === "WO-1")!;
  assert.deepEqual(wo1.pins, [
    { kind: "lab", id: "emory-biophys", revision: 1, digest: s.revisions["lab:emory-biophys"][0].digest },
    { kind: "project", id: "coomassie-reduction", revision: 1, digest: s.revisions["project:coomassie-reduction"][0].digest },
    { kind: "experiment", id: "coomassie-run-1", revision: 1, digest: s.revisions["experiment:coomassie-run-1"][0].digest },
    { kind: "skill", id: "procedure-style", revision: 1, digest: s.revisions["skill:procedure-style"][0].digest },
    { kind: "skill", id: "reporting-units", revision: 1, digest: s.revisions["skill:reporting-units"][0].digest },
  ]);
  for (const o of s.orders) assert.equal(o.pins.filter((p) => p.kind === "skill").length, 2);
});

test("no seeded step text contains an instrument value", async () => {
  const s = await createSeed(NOW);
  for (const sub of s.submissions) {
    if (sub.work_order_id === "WO-B12-RP") continue;
    for (const step of (sub.artifact as { steps: ProcedureStep[] }).steps) assert.doesNotMatch(step.text, TEXT_VALUE);
  }
  for (const key of Object.keys(s.views)) {
    for (const v of s.views[key]) if ("text" in v) assert.doesNotMatch(v.text, TEXT_VALUE);
  }
});

function docsFor(s: Awaited<ReturnType<typeof createSeed>>, experimentId: string): Document[] {
  const e = s.experiments.find((x) => x.id === experimentId)!;
  const p = s.projects.find((x) => x.id === e.project_id)!;
  return [...s.lab.documents, ...p.documents, ...e.documents];
}

test("every citation in a passing submission resolves to exactly one document", async () => {
  const s = await createSeed(NOW);
  for (const sub of s.submissions.filter((x) => x.passed)) {
    const order = s.orders.find((o) => o.id === sub.work_order_id)!;
    const docs = docsFor(s, order.experiment_id);
    for (const step of (sub.artifact as { steps: ProcedureStep[] }).steps) {
      assert.ok(step.citations.length > 0);
      for (const id of step.citations) assert.equal(docs.filter((d) => d.id === id).length, 1, id);
    }
  }
});

test("WO-1 submission 1 has the planned steps and exactly one failing result", async () => {
  const s = await createSeed(NOW);
  const sub = s.submissions.find((x) => x.work_order_id === "WO-1")!;
  assert.equal(sub.number, 1);
  assert.equal(sub.passed, false);
  const steps = (sub.artifact as { steps: ProcedureStep[] }).steps;
  assert.equal(steps.length, 5);
  assert.deepEqual(steps[0], {
    text: "Prepare the dye solution as described in the dye preparation note.",
    citations: ["coomassie-dye-prep"],
    amounts: [{ what: "dye solution", value: 1, unit: "mL" }],
  });
  assert.deepEqual([steps[1].text, steps[1].citations], ["Blank the spectrophotometer with solvent only.", ["sop-cuvette"]]);
  assert.deepEqual([steps[2].text, steps[2].citations], ["Bring the cuvette to temperature.", ["sop-cuvette"]]);
  assert.deepEqual([steps[3].text], ["Add the reducing agent and mix."]);
  assert.deepEqual([steps[4].text, steps[4].citations], ["Record absorbance as the blue fades.", ["coomassie-dye-prep"]]);
  assert.deepEqual(steps[2].action, {
    instrument_id: "uvvis-1", command: "set_temperature",
    settings: [{ parameter: "temperature", value: 298.15, unit: "K" }],
  });
  assert.deepEqual(steps[3].citations, []);
  assert.deepEqual(steps[4].action?.settings, [
    { parameter: "wavelength", value: 595, unit: "nm" },
    { parameter: "integration_time", value: 1, unit: "s" },
  ]);
  assert.equal(sub.artifact_digest, await canonicalDigest(sub.artifact));
  assert.equal(sub.results.length, 10);
  const failing = sub.results.filter((r) => !r.passed);
  assert.deepEqual(failing, [{ name: "step 4: citations", passed: false, detail: "no citation" }]);
  for (let n = 1; n <= 5; n += 1) assert.ok(sub.results.some((r) => r.name === `step ${n}: citations`));
  for (const name of ["step 2: wavelength", "step 3: temperature", "step 5: wavelength", "step 5: integration_time"]) {
    assert.equal(sub.results.find((r) => r.name === name)?.passed, true, name);
  }
  assert.ok(sub.results.some((r) => r.name === "step 1: amount dye solution"));
});

test("WO-B12 submission uses the backend procedure example and passes", async () => {
  const s = await createSeed(NOW);
  const sub = s.submissions.find((x) => x.work_order_id === "WO-B12")!;
  assert.equal(sub.passed, true);
  assert.deepEqual(sub.artifact, {
    steps: [
      { text: "Rinse the cuvette twice with buffer.", citations: ["sop-cuvette"] },
      { text: "Pipette the sample into the cuvette.", citations: ["b12-protocol"], amounts: [{ what: "sample", value: 1, unit: "mL" }] },
      {
        text: "Place the cuvette in the holder and read the absorbance.",
        citations: ["sop-cuvette"],
        action: { instrument_id: "uvvis-1", command: "read_absorbance", settings: [{ parameter: "wavelength", value: 550, unit: "nm" }] },
      },
    ],
  });
  assert.ok(sub.results.every((r) => r.passed));
  assert.equal(sub.artifact_digest, await canonicalDigest(sub.artifact));
});

test("WO-B12-RP fails step 1 wavelength and the view shows it", async () => {
  const s = await createSeed(NOW);
  const sub = s.submissions.find((x) => x.work_order_id === "WO-B12-RP")!;
  assert.deepEqual(sub.artifact, {
    instrument_id: "uvvis-1",
    steps: [{ command: "read_absorbance", settings: [{ parameter: "wavelength", value: 750, unit: "nm" }] }],
  });
  assert.equal(sub.passed, false);
  const failure = { name: "step 1: wavelength", passed: false, detail: "750 nm is above the maximum 700 nm" };
  assert.deepEqual(sub.results.filter((r) => !r.passed), [failure]);
  const view = s.views["WO-B12-RP#1"][0];
  assert.deepEqual(view.failures, [failure]);
  assert.deepEqual(view.settings[0], {
    parameter: "wavelength", display: "750 nm", canonical: { value: 750, unit: "nm", minimum: 400, maximum: 700 },
  });
});

test("views are keyed by order and submission, with sources, settings and unchecked", async () => {
  const s = await createSeed(NOW);
  assert.deepEqual(Object.keys(s.views).sort(), ["WO-1#1", "WO-B12#1", "WO-B12-RP#1"]);
  const v = s.views["WO-1#1"];
  assert.equal(v.length, 5);
  const first = v[0] as import("../types.ts").StepView;
  assert.deepEqual(first.sources, [{ id: "coomassie-dye-prep", title: "Dye stock preparation" }]);
  assert.deepEqual(first.unchecked, ["dye solution 1 mL"]);
  assert.deepEqual(first.settings, []);
  const second = v[1] as import("../types.ts").StepView;
  assert.deepEqual(second.sources, [{ id: "sop-cuvette", title: "Cuvette handling" }]);
  assert.equal(second.settings[0].display, "595 nm");
  assert.deepEqual(second.settings[0].canonical, { value: 595, unit: "nm", minimum: 400, maximum: 700 });
  const fourth = v[3] as import("../types.ts").StepView;
  assert.deepEqual(fourth.sources, []);
  assert.deepEqual(fourth.failures, [{ name: "step 4: citations", passed: false, detail: "no citation" }]);
  assert.deepEqual(v[0].failures, []);
});

test("history has created, claimed and submitted per order", async () => {
  const s = await createSeed(NOW);
  const expected: Record<string, [string, string]> = {
    "WO-1": ["factory", "failed"], "WO-B12": ["codex on lab-pc", "passed"], "WO-B12-RP": ["codex on lab-pc", "failed"],
  };
  for (const [id, [actor, note]] of Object.entries(expected)) {
    const h = s.history[id];
    assert.deepEqual(h.map((e) => e.event), ["created", "claimed", "submitted"]);
    assert.equal(h[1].actor, actor);
    assert.deepEqual([h[2].submission, h[2].note], [1, note]);
    const times = h.map((e) => Date.parse(e.at));
    assert.deepEqual([...times].sort((a, b) => a - b), times);
    assert.ok(times.every((t) => t < NOW.getTime()));
    const sub = s.submissions.find((x) => x.work_order_id === id)!;
    assert.equal(Date.parse(sub.submitted_at), times[2]);
  }
});

test("messages for coomassie-run-1 and b12-vial-a", async () => {
  const s = await createSeed(NOW);
  const m = s.messages["coomassie-run-1"];
  assert.equal(m.length, 3);
  assert.deepEqual([m[0].from, m[0].text], ["person", "Reduce the central carbon of Coomassie blue and follow it on the spectrophotometer."]);
  assert.equal(m[1].text, "I can build a procedure, an analysis app that fits the fading curve, and a simulation of the reaction.");
  assert.deepEqual(m[1].proposal, { outputs: ["procedure", "analysis_app", "simulation"], accepted: ["procedure", "analysis_app", "simulation"] });
  assert.equal(m[2].text, "Built. Step 4 has no source for the reducing agent. Attach the protocol or paper you’re working from and I’ll rewrite the procedure.");
  assert.deepEqual(m[2].activity?.map((a) => [a.label, a.outcome]), [
    ["Read lab context (revision 1)", "done"],
    ["Read project context (revision 1)", "done"],
    ["Wrote procedure", "done"],
    ["Ran 10 checks: 1 failed", "failed"],
    ["Wrote analysis app", "done"],
    ["Prepared 3 reference cases", "info"],
    ["Wrote simulation", "done"],
  ]);
  assert.deepEqual(m[2].activity?.[3].detail, "step 4: citations: no citation");
  assert.deepEqual(m[2].output_refs?.map((r) => [r.kind, r.work_order_id]), [
    ["procedure", "WO-1"], ["analysis_app", undefined], ["simulation", undefined],
  ]);
  assert.deepEqual(m[2].output_refs?.map((r) => r.summary), [
    "Submission 1, 1 check failed",
    "Turns absorbance over time into a rate constant and half-life.",
    "Fading curves for three amounts of reducing agent",
  ]);
  const times = m.map((x) => Date.parse(x.at));
  assert.deepEqual([...times].sort((a, b) => a - b), times);
  assert.ok(times.every((t) => t < NOW.getTime()));
  const b = s.messages["b12-vial-a"];
  assert.equal(b.length, 2);
  assert.equal(b[0].text, "Measure absorbance of the reference solution in vial A.");
  assert.deepEqual(b[1].output_refs?.map((r) => [r.kind, r.work_order_id]), [["procedure", "WO-B12"], ["run_plan", "WO-B12-RP"]]);
  assert.deepEqual(b[1].output_refs?.map((r) => r.summary), ["Submission 1, all checks passed", "Submission 1, 1 check failed"]);
});

test("the analysis app and simulation", async () => {
  const s = await createSeed(NOW);
  assert.deepEqual(Object.keys(s.apps), ["coomassie-run-1"]);
  assert.deepEqual(s.apps["coomassie-run-1"], {
    summary: "Turns absorbance over time into a rate constant and half-life.",
    code: ANALYSIS_CODE,
    entry: "analyze",
    reference_cases: [
      { name: "Clean decay", input: { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0, seed: 1 },
        expect: { decay: true, rate_constant_per_s: 0.01 }, rel_tol: 0.01 },
      { name: "Noisy decay", input: { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0.005, seed: 2 },
        expect: { decay: true, rate_constant_per_s: 0.01 }, rel_tol: 0.05 },
      { name: "No reaction", input: { k: 0, a0: 0.6, a_end: 0.6, noise: 0.003, seed: 3 },
        expect: { decay: false }, rel_tol: 0.05 },
    ],
  });
  assert.deepEqual(REFERENCE_CASES, s.apps["coomassie-run-1"].reference_cases);
  assert.deepEqual(s.simulations["coomassie-run-1"], {
    title: "Fading curves for three amounts of reducing agent",
    summary: "Predicted absorbance at the blue peak if the rate scales with the amount of reducing agent.",
    code: SIMULATION_CODE,
    entry: "simulate",
    x_label: "Time (s)",
    y_label: "Absorbance (AU)",
  });
});

test("skills and connectors", async () => {
  const s = await createSeed(NOW);
  assert.deepEqual(s.skills.map((k) => [k.id, k.title, k.enabled]), [
    ["procedure-style", "How we write procedures", true],
    ["reporting-units", "Units we report in", true],
    ["plot-style", "Plotting conventions", false],
  ]);
  assert.deepEqual(s.skills.map((k) => k.description), [
    "Short instructions with a source for every step.",
    "Concentrations in mg/L, rates per second.",
    "Units on every axis, points for data, lines for fits.",
  ]);
  assert.equal(s.skills[2].body, "- Label every axis with its unit.\n- Show measured data as points and fitted curves as lines.");
  assert.deepEqual(s.connectors.map((c) => [c.name, c.provides]), [
    ["Google Drive", "Protocols and papers"],
    ["Zotero", "Papers"],
    ["Lab notebook (Benchling and others)", "Notebook entries and protocols"],
    ["Instrument data folder", "Readings exported by your instruments"],
    ["GitHub", "Existing analysis code"],
  ]);
  assert.equal(s.skills[0].body, [
    "- Write each step as one short instruction.",
    "- Cite at least one lab, project or experiment document in every step.",
    "- Put instrument settings in the step's action, never in its text.",
    "- Put hand-measured quantities in amounts.",
  ].join("\n"));
  assert.equal(s.skills[1].body, "- Report concentrations in mg/L.\n- Report rate constants per second and half-lives in seconds.");
  assert.deepEqual(s.connectors.map((c) => [c.id, c.connected, c.account]), [
    ["google_drive", false, null],
    ["zotero", true, "Emory Biophysics library"],
    ["eln", false, null],
    ["instrument_folder", true, "uvvis-1 exports"],
    ["github", false, null],
  ]);
  assert.deepEqual(s.connectors.map((c) => c.items.map((i) => [i.id, i.kind, i.title])), [
    [["drive-dye-protocol", "sop", "Coomassie dye protocol (sample)"]],
    [["zotero-dye-reduction", "paper", "Reduction of triarylmethane dyes (sample)"]],
    [["eln-dye-stock", "note", "Notebook entry: dye stock (sample)"]],
    [["coomassie-run-1.csv", "readings", "coomassie-run-1.csv"]],
    [["gh-fit-utils", "code", "fit_utils.py (sample)"]],
  ]);
  assert.equal(s.connectors[3].items[0].text, toCsv(SAMPLE_READINGS));
});

test("two createSeed calls do not share objects, and a seed shares none internally", async () => {
  const collect = (root: unknown): Set<object> => {
    const seen = new Set<object>();
    let total = 0;
    const walk = (v: unknown): void => {
      if (v === null || typeof v !== "object") return;
      total += 1;
      seen.add(v);
      for (const c of Object.values(v)) walk(c);
    };
    walk(root);
    assert.equal(seen.size, total, "an object appears twice within one seed");
    return seen;
  };
  const a = collect(await createSeed(NOW));
  const b = collect(await createSeed(NOW));
  for (const o of a) assert.ok(!b.has(o));
});

test("procedureTemplate and runPlanTemplate pass for the sample and a different instrument", () => {
  const lab = (JSON.parse(JSON.stringify(readJson("uvvis-lab.json")))) as import("../types.ts").Lab;
  const other = {
    id: "plate-1", name: "Plate reader", model: "PR-1", firmware: "1.0", notes: "",
    parameters: [
      { name: "excitation", unit: "nm", minimum: 300, maximum: 500 },
      { name: "gain", unit: "dB", minimum: 1, maximum: 20 },
    ],
    commands: [
      { name: "read_plate", required: ["excitation", "gain"], optional: [] },
      { name: "shake", required: [], optional: [] },
    ],
  };
  for (const instrument of [lab.instruments[0], other]) {
    const steps = procedureTemplate(instrument, ["sop-cuvette", "b12-protocol"]);
    const docs: Document[] = [
      ...lab.documents,
      { id: "b12-protocol", kind: "sop", title: "P", source: "s", text: "t" },
    ];
    const results = procedureResults(steps, docs, [instrument], true);
    assert.ok(results.every((r) => r.passed), JSON.stringify(results.filter((r) => !r.passed)));
    for (const st of steps) {
      assert.ok(st.citations.length >= 1);
      assert.doesNotMatch(st.text, TEXT_VALUE);
    }
    const plan: RunPlan = runPlanTemplate(instrument);
    assert.equal(plan.instrument_id, instrument.id);
    assert.ok(runPlanResults(plan, [instrument]).every((r) => r.passed));
    assert.equal(plan.steps.length, instrument.commands.length);
  }
  const readAbs = runPlanTemplate(lab.instruments[0]).steps[0];
  assert.deepEqual(readAbs.settings, [{ parameter: "wavelength", value: 550, unit: "nm" }]);
});

test("timestamps derive from now", async () => {
  const s = await createSeed(NOW);
  const later = await createSeed(new Date(NOW.getTime() + 3600_000));
  const sub = (x: typeof s): Submission => x.submissions[0];
  assert.equal(Date.parse(sub(later).submitted_at) - Date.parse(sub(s).submitted_at), 3600_000);
  assert.match(sub(s).submitted_at, /^\d{4}-\d{2}-\d{2}T.*Z$/);
});
