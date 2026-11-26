import assert from "node:assert/strict";
import { test } from "node:test";

import { DRAW_LIMIT, TABLE_LIMIT, dataRows, drawnPoints, linearScale, plotAxes, samplingNote, seriesSummary, tableNote, tickLabel } from "./plot.ts";

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

test("dataRows joins series that share an x grid by index, one row per index", () => {
  const rows = dataRows([
    { label: "A", points: [[0, 1], [10, 2], [20, 3]], style: "line" },
    { label: "B", points: [[0, 4], [10, 5], [20, 6]], style: "line" },
  ]);
  assert.deepEqual(rows, [
    { x: 0, values: [1, 4] },
    { x: 10, values: [2, 5] },
    { x: 20, values: [3, 6] },
  ]);
});

test("dataRows keeps every point, in order, when the series don't share a grid", () => {
  const rows = dataRows([
    { label: "A", points: [[10, 2], [0, 1], [10, 7]], style: "points" },
    { label: "B", points: [[0, 3]], style: "line" },
  ]);
  assert.deepEqual(rows, [
    { x: 10, values: [2, null] },
    { x: 0, values: [1, null] },
    { x: 10, values: [7, null] },
    { x: 0, values: [null, 3] },
  ]);
});

test("dataRows never drops readings that share a time", () => {
  const rows = dataRows([{ label: "A", points: [[5, 1], [5, 2], [5, 3]], style: "points" }]);
  assert.deepEqual(rows, [{ x: 5, values: [1] }, { x: 5, values: [2] }, { x: 5, values: [3] }]);
});

test("plotAxes copes with 300,000 points without overflowing the stack", () => {
  const points = Array.from({ length: 300_000 }, (_, i) => [i, Math.sin(i) * 2] as [number, number]);
  const axes = plotAxes([{ label: "R", points, style: "points" }]);
  assert.ok(axes.x.domain[0] <= 0 && axes.x.domain[1] >= 299_999);
  assert.ok(axes.y.domain[0] <= -1.99 && axes.y.domain[1] >= 1.99);
});

test("plotAxes spans a negative domain", () => {
  const axes = plotAxes([{ label: "R", points: [[-60, -0.8], [-10, -0.05]], style: "points" }]);
  assert.ok(axes.x.domain[0] <= -60 && axes.x.domain[1] >= -10);
  assert.ok(axes.x.domain[1] <= 0);
  assert.ok(axes.y.domain[0] <= -0.8 && axes.y.domain[1] >= -0.05 && axes.y.domain[1] <= 0);
  assert.deepEqual(axes.y.ticks.map((t) => tickLabel(t, axes.y.ticks)), axes.y.ticks.map((t) => (t === 0 ? 0 : t).toFixed(1)));
});

test("tickLabel never writes a minus sign on zero", () => {
  assert.equal(tickLabel(-0, [-0.2, -0.1, 0]), "0.0");
  assert.equal(tickLabel(-0, [-200, -100, 0]), "0");
  assert.equal(tickLabel(-1e-17, [-0.2, -0.1, 0]), "0.0");
  assert.equal(tickLabel(-0.1, [-0.2, -0.1, 0]), "-0.1");
});

test("drawnPoints keeps small series whole and samples big ones evenly, first and last included", () => {
  const small = Array.from({ length: DRAW_LIMIT }, (_, i) => [i, i] as [number, number]);
  assert.equal(drawnPoints(small), small);
  const big = Array.from({ length: 300_000 }, (_, i) => [i, i * 2] as [number, number]);
  const drawn = drawnPoints(big);
  assert.equal(DRAW_LIMIT, 2000);
  assert.equal(drawn.length, 2000);
  assert.deepEqual(drawn[0], [0, 0]);
  assert.deepEqual(drawn.at(-1), [299_999, 599_998]);
  const gaps = drawn.slice(1).map((p, i) => p[0] - drawn[i][0]);
  assert.ok(Math.max(...gaps) - Math.min(...gaps) <= 1);
  assert.equal(drawnPoints(big.slice(0, 2001)).length, 2000);
});

test("the sampling and table notes say how much is shown", () => {
  assert.equal(samplingNote(20000), "Showing 2,000 of 20,000 readings. The analysis used all of them.");
  assert.equal(TABLE_LIMIT, 2000);
  assert.equal(tableNote(100000), "Showing the first 2,000 of 100,000 rows.");
});
