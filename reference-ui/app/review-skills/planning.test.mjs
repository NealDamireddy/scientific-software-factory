import test from "node:test";
import assert from "node:assert/strict";
import { planningSkills } from "./planning.ts";

const record = {
  runNumber: 3,
  kind: "b12",
  mode: "original",
  objective: "Estimate absorbance in a simulated B12 sample",
  project: "Simulated biophysics measurements",
  methodName: "B12 calibration",
  methodRevision: "2.3",
  wavelengthNm: 361,
  readings: [],
};
const method = planningSkills.find((skill) => skill.id === "method-reference");
const protocol = planningSkills.find(
  (skill) => skill.id === "protocol-readiness",
);

test("both planning skills run at start for original and repeat measurement records", () => {
  assert.equal(planningSkills.length, 2);
  assert.equal(method.family, "Lab knowledge");
  assert.equal(protocol.family, "Experiment planning");
  for (const skill of planningSkills) {
    assert.equal(skill.stage, "start");
    for (const kind of ["b12", "time-course"]) {
      for (const mode of ["original", "repeat"]) {
        assert.equal(
          skill.evaluate({ ...record, kind, mode }).verdict,
          "clear",
        );
      }
    }
    assert.equal(skill.evaluate({ ...record, kind: "unrelated" }), null);
  }
});

test("method reference cites the supplied name and exact revision independently of setup", () => {
  const result = method.evaluate({
    ...record,
    methodRevision: " 2.3b ",
    objective: undefined,
    wavelengthNm: NaN,
  });
  assert.equal(result.verdict, "clear");
  assert.deepEqual(result.references, [
    "Run 3 briefing · method name · B12 calibration",
    "Run 3 briefing · method revision · 2.3b",
  ]);
});

test("method reference identifies gaps without assigning a default revision or run number", () => {
  const partial = method.evaluate({
    ...record,
    runNumber: Infinity,
    methodRevision: "  ",
  });
  assert.equal(partial.verdict, "unassessed");
  assert.match(partial.finding, /method revision/);
  assert.deepEqual(partial.references, [
    "Run briefing · method name · B12 calibration",
  ]);
  const absent = method.evaluate({
    ...record,
    methodName: undefined,
    methodRevision: undefined,
  });
  assert.equal(absent.verdict, "unassessed");
  assert.match(absent.finding, /method name, method revision/);
  assert.deepEqual(absent.references, []);
});

test("protocol readiness cites every field in a complete briefing", () => {
  assert.deepEqual(protocol.evaluate(record).references, [
    `Run 3 briefing · objective · ${record.objective}`,
    `Run 3 briefing · project · ${record.project}`,
    "Run 3 briefing · method name · B12 calibration",
    "Run 3 briefing · method revision · 2.3",
    "Run 3 briefing · wavelength · 361 nm",
  ]);
});

test("protocol readiness names each absent field even when readings are available", () => {
  for (const wavelengthNm of [undefined, NaN, Infinity, -Infinity]) {
    const result = protocol.evaluate({
      ...record,
      objective: " ",
      project: undefined,
      methodName: "",
      methodRevision: "",
      wavelengthNm,
      readings: [{ x: 0, y: 0.1 }],
    });
    assert.equal(result.verdict, "unassessed");
    assert.match(
      result.finding,
      /objective, project, method name, method revision, wavelength/,
    );
    assert.deepEqual(result.references, []);
  }
});

test("a recorded nonpositive wavelength produces an evidence-backed finding alongside other gaps", () => {
  for (const wavelengthNm of [0, -12]) {
    const result = protocol.evaluate({ ...record, project: "", wavelengthNm });
    assert.equal(result.verdict, "finding");
    assert.match(result.finding, /must be positive/);
    assert.match(result.finding, /missing for project/);
    assert.ok(
      result.references.includes(
        `Run 3 briefing · wavelength · ${wavelengthNm} nm`,
      ),
    );
  }
});
