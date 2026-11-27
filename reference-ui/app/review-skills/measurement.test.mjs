import test from "node:test";
import assert from "node:assert/strict";
import { measurementSkills } from "./measurement.ts";

const [instrument, dilution] = measurementSkills;
const repeat = {
  kind: "b12",
  mode: "repeat",
  runNumber: 2,
  instrument: "UV–Vis spectrometer",
  methodName: "Vitamin B12 calibration",
  wavelengthNm: 361,
  readings: [
    { x: 6, y: 0.53 },
    { x: 8, y: 0.69 },
  ],
  sampleAU: 0.65,
  dilutionFactor: 2,
  reportedConcentration: 15,
};

test("start review cites instrument, method and wavelength for both simulated run kinds", () => {
  assert.equal(instrument.id, "instrument-record");
  assert.equal(instrument.stage, "start");
  assert.equal(instrument.family, "Instruments & execution");
  for (const mode of ["original", "repeat"]) {
    for (const [kind, methodName, wavelengthNm] of [
      ["b12", "Vitamin B12 calibration", 361],
      ["time-course", "Coomassie reduction kinetics", 595],
    ]) {
      const result = instrument.evaluate({
        ...repeat,
        mode,
        kind,
        methodName,
        wavelengthNm,
      });
      assert.equal(result.verdict, "clear");
      for (const value of [
        "Run 2",
        repeat.instrument,
        methodName,
        wavelengthNm + " nm",
      ]) {
        assert.ok(result.references.some((ref) => ref.includes(value)));
      }
    }
  }
});

test("start review identifies missing or unusable measurement context", () => {
  for (const [field, value, reason] of [
    ["instrument", undefined, /instrument/],
    ["instrument", "  ", /instrument/],
    ["instrument", "Unknown", /instrument/],
    ["methodName", "", /method/],
    ["wavelengthNm", NaN, /wavelength/],
    ["wavelengthNm", Infinity, /wavelength/],
    ["wavelengthNm", 0, /wavelength/],
  ]) {
    const result = instrument.evaluate({ ...repeat, [field]: value });
    assert.equal(result.verdict, "unassessed");
    assert.match(result.finding, reason);
  }
});

test("repeat review applies only to B12 repeats", () => {
  assert.equal(dilution.id, "dilution-calculation");
  assert.equal(dilution.stage, "repeat");
  assert.equal(dilution.family, "Analysis & results");
  assert.equal(dilution.evaluate({ ...repeat, kind: "time-course" }), null);
  assert.equal(dilution.evaluate({ ...repeat, mode: "original" }), null);
});

test("repeat review reproduces 15 µM and flags an uncorrected report", () => {
  const result = dilution.evaluate(repeat);
  assert.equal(result.verdict, "clear");
  for (const value of [
    "Run 2",
    "0.65 AU",
    "0.53 AU",
    "0.69 AU",
    "2×",
    "15 µM",
  ]) {
    assert.ok(result.references.some((ref) => ref.includes(value)));
  }
  const mismatch = dilution.evaluate({ ...repeat, reportedConcentration: 7.5 });
  assert.equal(mismatch.verdict, "finding");
  assert.match(mismatch.finding, /15 µM/);
});

test("uses adjacent standards from an unordered descending calibration and preserves row IDs", () => {
  const readings = Object.freeze([
    { x: 0, y: 1 },
    { x: 12, y: 0.1 },
    { x: 4, y: 0.5 },
  ]);
  const result = dilution.evaluate({
    ...repeat,
    readings,
    sampleAU: 0.3,
    dilutionFactor: 3,
    approvedDilutionFactor: 2,
    reportedConcentration: 24,
  });
  assert.equal(result.verdict, "clear");
  assert.ok(
    result.references.some(
      (ref) => ref.includes("Standard 2") && ref.includes("0.1 AU"),
    ),
  );
  assert.ok(
    result.references.some(
      (ref) => ref.includes("Standard 3") && ref.includes("0.5 AU"),
    ),
  );
  assert.ok(!result.references.some((ref) => ref.includes("Standard 1")));
});

test("accepts the calibration endpoints and zero", () => {
  const readings = [
    { x: 0, y: 0 },
    { x: 10, y: 1 },
  ];
  for (const point of readings) {
    const result = dilution.evaluate({
      ...repeat,
      readings,
      sampleAU: point.y,
      reportedConcentration: point.x * 2,
    });
    assert.equal(result.verdict, "clear");
  }
});

test("withholds extrapolation on either side, distinguishing a withheld result from an absent report", () => {
  for (const sampleAU of [0.1, 1.25]) {
    for (const [reportedConcentration, verdict] of [
      [null, "clear"],
      [15, "finding"],
      [undefined, "unassessed"],
      [NaN, "unassessed"],
    ]) {
      const result = dilution.evaluate({
        ...repeat,
        sampleAU,
        reportedConcentration,
        dilutionFactor: undefined,
      });
      assert.equal(result.verdict, verdict);
      assert.match(result.finding, /outside the measured range/);
      assert.ok(result.references.some((ref) => ref.includes("0.53 AU")));
      assert.ok(result.references.some((ref) => ref.includes("0.69 AU")));
    }
  }
});

test("incomplete, ambiguous or nonfinite evidence cannot clear a concentration check", () => {
  for (const overrides of [
    { readings: undefined },
    { readings: [] },
    { readings: [repeat.readings[0]] },
    { readings: [repeat.readings[0], null] },
    { readings: [...repeat.readings, { x: 9, y: Infinity }] },
    { readings: [...repeat.readings, { x: NaN, y: 0.9 }] },
    { readings: [...repeat.readings, { x: 9, y: 0.69 }] },
    { readings: [...repeat.readings, { x: 8, y: 0.8 }] },
    { readings: [...repeat.readings, { x: 7, y: 0.8 }] },
    { sampleAU: NaN },
    { sampleAU: undefined },
    { dilutionFactor: Infinity },
    { dilutionFactor: 0 },
    { dilutionFactor: -1 },
    { dilutionFactor: undefined },
    { dilutionFactor: Number.MAX_VALUE },
    { reportedConcentration: Infinity },
    { reportedConcentration: undefined },
    { reportedConcentration: null },
  ]) {
    assert.equal(
      dilution.evaluate({ ...repeat, ...overrides }).verdict,
      "unassessed",
    );
  }
});
