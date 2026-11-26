import assert from "node:assert/strict";
import { test } from "node:test";

import { expectedLabel, foundLabel, referencePassed } from "./reference.ts";
import type { AnalysisResult } from "./analysis.ts";
import type { ReferenceCase } from "./types.ts";

const found = (k: number): AnalysisResult => ({ decay: true, rate_constant_per_s: k, half_life_s: Math.LN2 / k, a0: 0.8, a_end: 0.05, rms_error: 0 });

const decay: ReferenceCase = {
  name: "Clean decay", input: { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0, seed: 1 },
  expect: { decay: true, rate_constant_per_s: 0.01 }, rel_tol: 0.05,
};
const flat: ReferenceCase = { ...decay, name: "No reaction", expect: { decay: false } };

test("a decay case passes when the found rate is within rel_tol of the expected one", () => {
  assert.equal(referencePassed(decay, found(0.0104)), true);
  assert.equal(referencePassed(decay, found(0.0105)), true);
  assert.equal(referencePassed(decay, found(0.0106)), false);
  assert.equal(referencePassed(decay, found(0.0094)), false);
  assert.equal(referencePassed(decay, { decay: false, rms_error: 0 }), false);
});

test("a no-decay case passes only when no decay is found", () => {
  assert.equal(referencePassed(flat, { decay: false, rms_error: 0.01 }), true);
  assert.equal(referencePassed(flat, found(0.01)), false);
});

test("the expected and found values read in words", () => {
  assert.equal(expectedLabel(decay), "0.01 per s");
  assert.equal(expectedLabel(flat), "no decay");
  assert.equal(foundLabel(found(0.0100321)), "0.0100 per s");
  assert.equal(foundLabel({ decay: false, rms_error: 0 }), "no decay");
});
