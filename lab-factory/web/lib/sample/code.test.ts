import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { ANALYSIS_CODE, SIMULATION_CODE } from "./code.ts";

const pythonDir = join(import.meta.dirname, "..", "..", "python");

test("ANALYSIS_CODE equals python/analysis.py byte for byte", () => {
  assert.equal(ANALYSIS_CODE, readFileSync(join(pythonDir, "analysis.py"), "utf8"));
});

test("SIMULATION_CODE equals python/simulation.py byte for byte", () => {
  assert.equal(SIMULATION_CODE, readFileSync(join(pythonDir, "simulation.py"), "utf8"));
});
