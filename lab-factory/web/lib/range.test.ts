import assert from "node:assert/strict";
import { test } from "node:test";

import { markerPosition } from "./range.ts";

function close(actual: number, expected: number): void {
  assert.ok(Math.abs(actual - expected) <= 1e-9, `${actual} is not within 1e-9 of ${expected}`);
}

test("minimum maps to 0", () => close(markerPosition(400, 400, 700), 0));
test("maximum maps to 1", () => close(markerPosition(700, 400, 700), 1));
test("595 in 400–700 maps to 0.65", () => close(markerPosition(595, 400, 700), 0.65));
test("298.15 in 278.15–303.15 maps to 0.8", () => close(markerPosition(298.15, 278.15, 303.15), 0.8));
test("below the range clamps to 0", () => close(markerPosition(399, 400, 700), 0));
test("above the range clamps to 1", () => close(markerPosition(701, 400, 700), 1));
test("a degenerate range maps to 0.5", () => close(markerPosition(5, 5, 5), 0.5));
test("NaN maps to 0", () => close(markerPosition(Number.NaN, 400, 700), 0));
