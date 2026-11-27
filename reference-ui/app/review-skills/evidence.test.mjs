import test from "node:test";
import assert from "node:assert/strict";
import { evidenceSkills, reviewEvidencePacket } from "./evidence.ts";
import { researchSkills } from "./catalog.ts";
const ids = ["data-provenance", "claim-evidence"];
const source = "survey.csv",
  one = { row: 2, sample: "Lake A", measurement: "Depth", value: 0, unit: "m" };
const other = {
  row: 3,
  sample: "Lake B",
  measurement: "Depth",
  value: 7,
  unit: "m",
};
const claim = { sample: "Lake A", measurement: "Depth", value: 0, unit: "m" };
const packet = (extra = {}) => ({
  source,
  observations: [{ ...one }, { ...other }],
  claim: { ...claim },
  ...extra,
});
const checks = (p) => reviewEvidencePacket(p, ids);
const claimCheck = (p) => checks(p)[1];

test("checks supplied non-demo data and grounds a zero-valued claim to its actual row", () => {
  const [trace, match] = checks(packet());
  assert.equal(trace.verdict, "clear");
  assert.deepEqual(trace.references, [
    "survey.csv · row 2",
    "survey.csv · row 3",
  ]);
  assert.equal(match.verdict, "clear");
  assert.deepEqual(match.references, ["survey.csv · row 2"]);
  const mismatch = claimCheck(packet({ claim: { ...claim, value: 1.5 } }));
  assert.equal(mismatch.verdict, "finding");
  assert.match(mismatch.finding, /1.5 m/);
  assert.match(mismatch.finding, /0 m/);
});
test("cites every matching row and never chooses among duplicates", () => {
  for (const value of [0, 2]) {
    const c = claimCheck(
      packet({ observations: [one, other, { ...one, row: 8, value }] }),
    );
    assert.equal(c.verdict, "unassessed");
    assert.deepEqual(c.references, [
      "survey.csv · row 2",
      "survey.csv · row 8",
    ]);
  }
  const [provenance, c] = checks(
    packet({ observations: [one, { ...other, row: 2 }] }),
  );
  assert.equal(provenance.verdict, "finding");
  assert.equal(c.verdict, "unassessed");
  assert.match(c.finding, /shares its source row/);
});
test("does not convert incompatible units, merge case-sensitive identifiers or round a disagreement", () => {
  const unit = claimCheck(packet({ claim: { ...claim, unit: "M" } }));
  assert.equal(unit.verdict, "unassessed");
  assert.match(unit.finding, /no matching unit/);
  assert.equal(
    claimCheck(packet({ claim: { ...claim, sample: "lake a" } })).verdict,
    "unassessed",
  );
  assert.equal(
    claimCheck(packet({ claim: { ...claim, sample: " Lake A " } })).verdict,
    "clear",
  );
  assert.equal(
    claimCheck(packet({ claim: { ...claim, value: 1e-15 } })).verdict,
    "finding",
  );
});
test("flags malformed rows and withholds claims where evidence cannot be traced or compared", () => {
  for (const invalid of [
    { row: 0 },
    { row: 2.5 },
    { row: NaN },
    { value: NaN },
    { value: null },
    { value: Infinity },
    { unit: " " },
    { sample: "" },
    { measurement: "" },
  ]) {
    const [trace, c] = checks(
      packet({ observations: [{ ...one, ...invalid }] }),
    );
    assert.equal(trace.verdict, "finding");
    assert.equal(c.verdict, "unassessed");
  }
  for (const input of [
    packet({ source: " " }),
    packet({ observations: [] }),
    packet({ observations: null }),
    null,
  ]) {
    assert.deepEqual(
      checks(input).map((c) => c.verdict),
      ["unassessed", "unassessed"],
    );
  }
  for (const fields of [
    { value: Infinity },
    { value: null },
    { sample: "" },
    { measurement: "" },
    { unit: "" },
  ]) {
    assert.equal(
      claimCheck(packet({ claim: { ...claim, ...fields } })).verdict,
      "unassessed",
    );
  }
  assert.equal(claimCheck(packet({ claim: undefined })).verdict, "unassessed");
});
test("only enabled packet skills run, and supplied packets reuse the catalog evaluators", () => {
  const p = packet();
  assert.deepEqual(reviewEvidencePacket(p, []), []);
  assert.equal(
    reviewEvidencePacket(p, ["unknown", "data-provenance", "data-provenance"])
      .length,
    1,
  );
  const run = {
    runNumber: 5,
    kind: "time-course",
    mode: "original",
    readings: [],
  };
  for (const def of evidenceSkills) {
    assert.equal(researchSkills.filter((d) => d.id === def.id).length, 1);
    const { skillId, ...expected } = reviewEvidencePacket(p, [def.id])[0];
    assert.equal(skillId, def.id);
    assert.deepEqual(def.evaluate({ ...run, evidencePacket: p }), expected);
    const missing = def.evaluate(run);
    assert.equal(missing.verdict, "unassessed");
    assert.deepEqual(missing.references, ["Run 5 · run record"]);
  }
});

function meanPacket(values, reported) {
  return packet({
    claim: { ...claim, value: reported, statistic: "mean" },
    observations: values.map((value, i) => ({ ...one, row: i + 2, value })),
  });
}
test("an explicit mean uses every matching group row, cites its source and reports n", () => {
  const data = meanPacket([0.1, 0.2], 0.15);
  data.observations.push(
    { ...other, row: 9, value: 1000 },
    { ...one, row: 10, measurement: "Height", value: 200 },
  );
  const finding = claimCheck(data);
  assert.equal(finding.verdict, "clear");
  assert.match(finding.finding, /2 observations/);
  assert.deepEqual(finding.references, [
    "survey.csv · row 2",
    "survey.csv · row 3",
  ]);
  data.claim.value = 0.151;
  assert.equal(claimCheck(data).verdict, "finding");
  delete data.claim.statistic;
  assert.equal(claimCheck(data).verdict, "unassessed");
});
test("a mean never drops invalid values, pooled units or duplicate source addresses", () => {
  for (const issue of [
    { unit: "cm" },
    { unit: "" },
    { row: 2 },
    { row: 0 },
    { value: null },
    { value: NaN },
    { value: Infinity },
  ]) {
    const data = meanPacket([2, 4, 6], 3);
    Object.assign(data.observations[1], issue);
    assert.equal(claimCheck(data).verdict, "unassessed");
  }
  for (const values of [[], [2]])
    assert.equal(claimCheck(meanPacket(values, 2)).verdict, "unassessed");
  const data = meanPacket([2, 4], 3);
  data.observations.push({ ...other, row: 2 });
  assert.equal(claimCheck(data).verdict, "unassessed");
  data.claim.statistic = "median";
  assert.equal(claimCheck(data).verdict, "unassessed");
});
test("mean arithmetic is robust to overflow, cancellation, tiny values and ordering", () => {
  const max = Number.MAX_VALUE;
  for (const [values, reported] of [
    [[max, max], max],
    [[max, 3, -max], 1],
    [[-max, max, 3], 1],
    [[1e-300, 1e-300], 1e-300],
    [[Number.MIN_VALUE, Number.MIN_VALUE], Number.MIN_VALUE],
  ]) {
    assert.equal(claimCheck(meanPacket(values, reported)).verdict, "clear");
  }
  assert.equal(claimCheck(meanPacket([1e-300, 1e-300], 0)).verdict, "finding");
  assert.equal(claimCheck(meanPacket([2, 4], 3.0000001)).verdict, "finding");
});
