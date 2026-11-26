import assert from "node:assert/strict";
import { test } from "node:test";

import { fittedPoints, readAnalysisResult, readSimulation, resultLines } from "./analysis.ts";

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
