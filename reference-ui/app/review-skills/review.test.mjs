import assert from "node:assert/strict";
import test from "node:test";
import { reviewSkills } from "./review.ts";

const original = {
  runNumber: 3,
  kind: "b12",
  mode: "original",
  readings: [
    { x: 5, y: 0.45 },
    { x: 10, y: 0.85 },
    { x: 0, y: 0.05 },
  ],
  sampleAU: 1.25,
  reportedConcentration: null,
};
const repeat = {
  ...original,
  runNumber: 4,
  mode: "repeat",
  sampleAU: 0.65,
  reportedConcentration: 15,
  dilutionFactor: 2,
  approvedDilutionFactor: 2,
  original: { runNumber: 3, sampleAU: 1.25, outcome: "flagged" },
};
const adherence = reviewSkills.find((skill) => skill.id === "method-adherence");
const comparison = reviewSkills.find(
  (skill) => skill.id === "repeat-comparison",
);

test("skills apply to the specified families, stages and B12 run modes", () => {
  assert.deepEqual(
    [adherence.family, adherence.stage],
    ["Scientific review", "result"],
  );
  assert.deepEqual(
    [comparison.family, comparison.stage],
    ["Evidence & reproducibility", "repeat"],
  );
  assert.equal(comparison.evaluate(original), null);
  for (const skill of reviewSkills)
    assert.equal(skill.evaluate({ ...repeat, kind: "time-course" }), null);
});

test("above-range withholding clears and an extrapolated numeric report yields one finding", () => {
  assert.equal(adherence.evaluate(original).verdict, "clear");
  const findings = reviewSkills
    .map((skill) => skill.evaluate({ ...original, reportedConcentration: 15 }))
    .filter((result) => result?.verdict === "finding");
  assert.equal(findings.length, 1);
  assert.match(findings[0].finding, /above.*15 µM.*withheld/);
  const refs = findings[0].references.join(" ");
  for (const evidence of ["Run 3", "0.050–0.850 AU", "1.250 AU", "15 µM"])
    assert.ok(refs.includes(evidence));
});

test("in-range repeat clears, including both measured range limits", () => {
  for (const sampleAU of [0.05, 0.65, 0.85]) {
    assert.equal(adherence.evaluate({ ...repeat, sampleAU }).verdict, "clear");
  }
  assert.equal(
    adherence.evaluate({ ...repeat, sampleAU: 0.049 }).verdict,
    "finding",
  );
});

test("incomplete calibration or reporting evidence leaves the decision unassessed", () => {
  for (const patch of [
    { readings: undefined },
    { readings: [] },
    { readings: [original.readings[0]] },
    { readings: [original.readings[0], { x: NaN, y: 0.85 }] },
    { readings: [original.readings[0], { x: 8, y: Infinity }] },
    {
      readings: [
        { x: 0, y: 0.1 },
        { x: 1, y: 0.1 },
      ],
    },
    {
      readings: [
        { x: 1, y: 0.1 },
        { x: 1, y: 0.2 },
      ],
    },
    { sampleAU: undefined },
    { sampleAU: NaN },
    { runNumber: NaN },
    { reportedConcentration: undefined },
    { reportedConcentration: Infinity },
  ])
    assert.equal(
      adherence.evaluate({ ...original, ...patch }).verdict,
      "unassessed",
    );
});

test("repeat comparison cites actual run evidence and uses the supplied approval and bounds", () => {
  const result = comparison.evaluate({
    ...repeat,
    sampleAU: 0.95,
    dilutionFactor: 3,
    approvedDilutionFactor: 3,
    readings: [
      { x: 0, y: 0.1 },
      { x: 12, y: 1.1 },
    ],
  });
  assert.equal(result.verdict, "clear");
  const refs = result.references.join(" ");
  for (const evidence of [
    "Original run 3",
    "flagged",
    "1.250 AU",
    "Run 4",
    "approved dilution 3×",
    "actual dilution 3×",
    "0.950 AU",
    "0.100–1.100 AU",
  ])
    assert.ok(refs.includes(evidence));
});

test("a cancelled original with a recorded sample raises a finding on an otherwise valid repeat", () => {
  const result = comparison.evaluate({
    ...repeat,
    original: { ...repeat.original, outcome: "cancelled" },
  });
  assert.equal(result.verdict, "finding");
  assert.match(result.finding, /cancelled/);
  assert.match(result.finding, /flagged/);
  assert.ok(result.references.includes("Original run 3 · outcome cancelled"));
});

test("repeat comparison reports every observed issue and identifies missing evidence", () => {
  const result = comparison.evaluate({
    ...repeat,
    sampleAU: 0.02,
    dilutionFactor: 4,
    original: undefined,
  });
  assert.equal(result.verdict, "finding");
  assert.match(result.finding, /4×.*approved 2×/);
  assert.match(result.finding, /below.*range/);
  assert.match(result.finding, /original run record is missing/);
  assert.equal(
    comparison.evaluate({ ...repeat, sampleAU: 0.9 }).verdict,
    "finding",
  );
  assert.equal(
    comparison.evaluate({
      ...repeat,
      dilutionFactor: 0,
      approvedDilutionFactor: 0,
    }).verdict,
    "finding",
  );
  assert.equal(
    comparison.evaluate({
      ...repeat,
      original: { ...repeat.original, runNumber: 4 },
    }).verdict,
    "finding",
  );
});

test("missing or nonfinite repeat evidence cannot clear", () => {
  for (const patch of [
    { original: undefined },
    { original: { ...repeat.original, sampleAU: NaN } },
    { original: { ...repeat.original, outcome: "" } },
    { original: { ...repeat.original, runNumber: Infinity } },
    { approvedDilutionFactor: undefined },
    { dilutionFactor: NaN },
    { sampleAU: -Infinity },
    { runNumber: Infinity },
    { readings: [] },
    { readings: [original.readings[0], { x: 12, y: NaN }] },
  ])
    assert.equal(
      comparison.evaluate({ ...repeat, ...patch }).verdict,
      "unassessed",
    );
});
