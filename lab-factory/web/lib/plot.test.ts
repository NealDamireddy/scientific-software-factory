import assert from "node:assert/strict";
import { test } from "node:test";

import { dataRows, linearScale, plotAxes, seriesSummary, tickLabel } from "./plot.ts";

test("linearScale maps the domain onto the range, either way round", () => {
  const x = linearScale([0, 600], [50, 650]);
  assert.equal(x(0), 50);
  assert.equal(x(300), 350);
  const y = linearScale([0, 1], [300, 0]);
  assert.equal(y(0.25), 225);
  const flat = linearScale([2, 2], [0, 100]);
  assert.equal(flat(2), 50);
});

test("plotAxes spans the data with nice ticks at both ends", () => {
  const axes = plotAxes([{ label: "R", points: [[0, 0.05], [600, 0.8]], style: "points" }]);
  assert.deepEqual(axes.x.ticks, [0, 100, 200, 300, 400, 500, 600]);
  assert.deepEqual(axes.x.domain, [0, 600]);
  assert.equal(axes.y.ticks[0], 0);
  assert.equal(axes.y.ticks.at(-1), 0.8);
  assert.deepEqual(axes.y.domain, [0, 0.8]);
});

test("plotAxes widens a flat or empty series to a visible span", () => {
  const flat = plotAxes([{ label: "R", points: [[0, 0.5], [10, 0.5]], style: "points" }]);
  assert.ok(flat.y.domain[0] < 0.5 && flat.y.domain[1] > 0.5);
  const none = plotAxes([]);
  assert.ok(none.x.domain[1] > none.x.domain[0]);
});

test("tickLabel writes ticks with the decimals their step needs", () => {
  assert.equal(tickLabel(0.30000000000000004, [0, 0.1, 0.2]), "0.3");
  assert.equal(tickLabel(0.05, [0, 0.05, 0.1]), "0.05");
  assert.equal(tickLabel(0.1, [0, 0.05, 0.1]), "0.10");
  assert.equal(tickLabel(200, [0, 100, 200]), "200");
});

test("seriesSummary names the plot and each series", () => {
  assert.equal(seriesSummary("Readings and fit", [
    { label: "Readings", points: Array.from({ length: 61 }, (_, i) => [i, 1] as [number, number]), style: "points" },
    { label: "Fit", points: [[0, 1]], style: "line" },
  ]), "Readings and fit. Readings: 61 points. Fit: line.");
  assert.equal(seriesSummary("Empty", []), "Empty. No data.");
  assert.equal(seriesSummary("One", [{ label: "A", points: [[0, 1]], style: "points" }]), "One. A: 1 point.");
});

test("dataRows lines the series up by x value, one row per x", () => {
  const rows = dataRows([
    { label: "A", points: [[10, 2], [0, 1]], style: "points" },
    { label: "B", points: [[0, 3], [20, 4]], style: "line" },
  ]);
  assert.deepEqual(rows, [
    { x: 0, values: [1, 3] },
    { x: 10, values: [2, null] },
    { x: 20, values: [null, 4] },
  ]);
});
