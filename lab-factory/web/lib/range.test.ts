import assert from "node:assert/strict";
import { test } from "node:test";

import { markerPosition, spectrumLayer } from "./range.ts";
import type { SpectrumLayer } from "./range.ts";

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

// spectrumLayer places the 400 to 700 nm spectrum on a track that runs from minimum to maximum.
// Where the whole spectrum image lands on the track, as fractions of the track, and which band shows it.
function placed(layer: SpectrumLayer): { band: [number, number]; spectrum: [number, number] } {
  const band = layer.width / 100;
  const left = layer.left / 100;
  const image = (layer.sizePercent / 100) * band;
  const offset = (band - image) * (layer.positionPercent / 100);
  return { band: [left, left + band], spectrum: [left + offset, left + offset + image] };
}

function closePair(actual: [number, number], expected: [number, number]): void {
  close(actual[0], expected[0]);
  close(actual[1], expected[1]);
}

test("a 400 to 700 nm range shows the whole spectrum across the track", () => {
  assert.deepEqual(spectrumLayer(400, 700), { left: 0, width: 100, sizePercent: 100, positionPercent: 0 });
});

test("a range wider than the spectrum draws it only over the 400 to 700 part of the track", () => {
  const p = placed(spectrumLayer(190, 1100)!);
  closePair(p.band, [(400 - 190) / 910, (700 - 190) / 910]);
  closePair(p.spectrum, p.band);
});

test("a range that starts inside the spectrum and ends past it shows the spectrum's end, then the plain track", () => {
  const p = placed(spectrumLayer(550, 850)!);
  closePair(p.band, [0, 0.5]);
  closePair(p.spectrum, [-0.5, 0.5]);
});

test("a range that starts below the spectrum and ends inside it shows the plain track, then the spectrum's start", () => {
  const p = placed(spectrumLayer(300, 600)!);
  closePair(p.band, [1 / 3, 1]);
  closePair(p.spectrum, [1 / 3, 4 / 3]);
});

test("a range inside the spectrum shows the matching slice", () => {
  const p = placed(spectrumLayer(500, 600)!);
  closePair(p.band, [0, 1]);
  closePair(p.spectrum, [-1, 2]);
});

test("a range outside the spectrum, or an empty one, gets no spectrum", () => {
  assert.equal(spectrumLayer(700, 1100), null);
  assert.equal(spectrumLayer(200, 400), null);
  assert.equal(spectrumLayer(500, 500), null);
  assert.equal(spectrumLayer(Number.NaN, 600), null);
});
