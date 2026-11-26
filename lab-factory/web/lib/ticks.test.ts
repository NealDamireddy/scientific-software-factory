import assert from "node:assert/strict";
import { test } from "node:test";

import { niceTicks } from "./ticks.ts";

test("0 to 600 steps by 100", () => {
  assert.deepEqual(niceTicks(0, 600), [0, 100, 200, 300, 400, 500, 600]);
});

test("0.05 to 0.8 steps by 0.2 without float noise", () => {
  assert.deepEqual(niceTicks(0.05, 0.8), [0, 0.2, 0.4, 0.6, 0.8]);
});

test("an empty range gives one tick", () => {
  assert.deepEqual(niceTicks(3, 3), [3]);
});
