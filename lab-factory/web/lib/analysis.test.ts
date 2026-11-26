import assert from "node:assert/strict";
import { test } from "node:test";

import { analysisMessage, completionLine, fitLine, fittedPoints, readAnalysisResult, readSimulation, readingRows, resultLines } from "./analysis.ts";

const decay = { decay: true, rate_constant_per_s: 0.0085123, half_life_s: 81.43, a0: 0.8, a_end: 0.05, rms_error: 0.00231 };

test("readAnalysisResult accepts the analysis app's answer and refuses anything else", () => {
  assert.deepEqual(readAnalysisResult(decay), decay);
  assert.deepEqual(readAnalysisResult({ decay: false, rms_error: 0.01 }), { decay: false, rms_error: 0.01 });
  for (const bad of [null, 3, "x", {}, { decay: "yes", rms_error: 1 }, { decay: true, rms_error: 1 },
    { decay: true, rate_constant_per_s: Number.NaN, half_life_s: 1, a0: 1, a_end: 0, rms_error: 1 },
    { decay: false }]) {
    assert.equal(readAnalysisResult(bad), null, JSON.stringify(bad));
  }
});

test("resultLines reads the result to 3 significant figures", () => {
  assert.deepEqual(resultLines(decay), ["Rate constant 0.00851 per s", "Half-life 81.4 s", "Fit error (RMS) 0.00231 AU"]);
  assert.deepEqual(resultLines({ decay: false, rms_error: 0.0123 }), ["No decay detected", "Fit error (RMS) 0.0123 AU"]);
});

test("fittedPoints draws the app's own curve at the readings' times", () => {
  const points = fittedPoints({ ...decay, rate_constant_per_s: 0.01 }, [0, 100]);
  assert.equal(points.length, 2);
  assert.deepEqual(points[0], [0, 0.8]);
  assert.ok(Math.abs(points[1][1] - (0.05 + 0.75 * Math.exp(-1))) < 1e-12);
  assert.deepEqual(fittedPoints({ decay: false, rms_error: 0 }, [0, 100]), []);
});

test("readSimulation reads labelled series of points", () => {
  const value = { series: [{ label: "0.5 mM", points: [[0, 0.8], [10, 0.7]] }] };
  assert.deepEqual(readSimulation(value), [{ label: "0.5 mM", points: [[0, 0.8], [10, 0.7]] }]);
  for (const bad of [null, {}, { series: {} }, { series: [{ label: 1, points: [] }] }, { series: [{ label: "a", points: [[0]] }] }]) {
    assert.equal(readSimulation(bad), null, JSON.stringify(bad));
  }
});

test("fitLine draws the fit on a sorted grid of 200 times from the first to the last reading", () => {
  const result = { ...decay, rate_constant_per_s: 0.01 };
  const line = fitLine(result, [300, 0, 600, 100]);
  assert.equal(line.length, 200);
  assert.deepEqual(line[0], [0, 0.8]);
  assert.equal(line.at(-1)?.[0], 600);
  for (let i = 1; i < line.length; i += 1) assert.ok(line[i][0] > line[i - 1][0]);
  for (const [t, a] of line) assert.ok(Math.abs(a - (0.05 + 0.75 * Math.exp(-0.01 * t))) < 1e-12);
  assert.deepEqual(fitLine({ decay: false, rms_error: 0 }, [0, 10]), []);
});

test("fitLine is dense even when the readings are sparse", () => {
  const line = fitLine({ ...decay, rate_constant_per_s: 0.01 }, [0, 1000]);
  assert.equal(line.length, 200);
  const step = 1000 / 199;
  line.forEach(([t], i) => assert.ok(Math.abs(t - i * step) < 1e-9));
});

test("readingRows keeps one row per reading in file order, with the fitted value at that time", () => {
  const result = { ...decay, rate_constant_per_s: 0.01 };
  const rows = readingRows({ time_s: [100, 0, 100], absorbance: [0.33, 0.8, 0.34] }, result);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map((r) => [r.x, r.values[0]]), [[100, 0.33], [0, 0.8], [100, 0.34]]);
  assert.ok(Math.abs((rows[0].values[1] ?? 0) - (0.05 + 0.75 * Math.exp(-1))) < 1e-12);
  assert.equal(rows[1].values[1], 0.8);
  assert.deepEqual(readingRows({ time_s: [0, 10], absorbance: [1, 1] }, { decay: false, rms_error: 0 }),
    [{ x: 0, values: [1] }, { x: 10, values: [1] }]);
});

test("completionLine says which file was analyzed and what was found", () => {
  assert.equal(completionLine("run.csv", decay), "Analyzed run.csv. Rate constant 0.00851 per s.");
  assert.equal(completionLine("flat.csv", { decay: false, rms_error: 0.01 }), "Analyzed flat.csv. No decay detected.");
});

test("analysisMessage rewords the all-times-equal error and passes other messages through", () => {
  assert.equal(analysisMessage("time_s must increase."), "The time_s values are all the same. The analysis needs readings at different times.");
  assert.equal(analysisMessage("The analysis needs at least 5 readings."), "The analysis needs at least 5 readings.");
});
