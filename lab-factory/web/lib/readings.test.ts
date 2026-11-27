import assert from "node:assert/strict";
import { test } from "node:test";

import { ClientError } from "./types.ts";
import { SAMPLE_READINGS, parseReadingsCsv, syntheticReadings, toCsv } from "./readings.ts";

function invalid(message: string) {
  return (error: unknown) => {
    assert.ok(error instanceof ClientError, "expected a ClientError");
    assert.equal(error.code, "invalid");
    assert.equal(error.message, message);
    return true;
  };
}

test("synthetic readings use the default step and duration", () => {
  const r = syntheticReadings({ k: 0.01, a0: 0.8, a_end: 0.05, noise: 0, seed: 1 });
  assert.equal(r.time_s.length, 61);
  assert.equal(r.time_s[0], 0);
  assert.equal(r.time_s[60], 600);
  assert.equal(r.absorbance[0], 0.8);
  assert.equal(r.absorbance[10], Math.round((0.05 + 0.75 * Math.exp(-1)) * 1e4) / 1e4);
});

test("noise is seeded, bounded and rounded to 4 decimals", () => {
  const p = { k: 0.0085, a0: 0.8, a_end: 0.05, noise: 0.004, seed: 7 };
  assert.deepEqual(syntheticReadings(p), syntheticReadings(p));
  assert.deepEqual(SAMPLE_READINGS, syntheticReadings(p));
  const clean = syntheticReadings({ ...p, noise: 0 });
  SAMPLE_READINGS.absorbance.forEach((a, i) => {
    assert.ok(Math.abs(a - clean.absorbance[i]) <= 0.004 + 1e-4);
    assert.equal(Math.round(a * 1e4) / 1e4, a);
  });
});

test("the CSV round-trips", () => {
  const csv = toCsv(SAMPLE_READINGS);
  assert.ok(csv.startsWith("time_s,absorbance\n"));
  assert.ok(!csv.includes("\r"));
  assert.deepEqual(parseReadingsCsv(csv), SAMPLE_READINGS);
});

test("quoted metadata, escapes and multiline fields preserve numeric column positions", () => {
  const text = '"sample,label",replicate,"time_s","absorbance"\r\n'
    + '"batch,A",1,10,0.7\r\n"batch ""B""",2," 20 ","0.6"\r\n'
    + '"batch\r\nC",3,30,0.5\r\nplain,4,40,0.4\r\n"batch,E",5,50,0.3';
  assert.deepEqual(parseReadingsCsv(text), { time_s: [10, 20, 30, 40, 50], absorbance: [0.7, 0.6, 0.5, 0.4, 0.3] });
  assert.throws(() => parseReadingsCsv(text + "\nplain,6,bad,0.2"), invalid("Row 8 has a value that isn't a number."));
});

test("inconsistent widths, duplicate numeric columns and malformed quotes are rejected", () => {
  const header = "sample,time_s,absorbance\n";
  assert.throws(() => parseReadingsCsv(header + "batch,A,10,0.7"), invalid("Row 2 has 4 fields. The header has 3."));
  assert.throws(() => parseReadingsCsv(header + "batch,10"), invalid("Row 2 has 2 fields. The header has 3."));
  assert.throws(() => parseReadingsCsv(header + '"batch,10,0.7'), invalid("Row 2 has an unclosed quoted field."));
  assert.throws(() => parseReadingsCsv(header + '"batch"x,10,0.7'), invalid("Row 2 has an invalid quoted field."));
  assert.throws(() => parseReadingsCsv("time_s,absorbance,time_s"), invalid("The file needs exactly one time_s column and one absorbance column."));
});

test("a missing column gives the column error", () => {
  assert.throws(
    () => parseReadingsCsv("time_s,signal\n0,1\n10,2\n20,3\n30,4\n40,5\n"),
    invalid("The file needs a time_s column and an absorbance column."),
  );
});

test("a text value names its row, counting the header as row 1", () => {
  assert.throws(
    () => parseReadingsCsv("time_s,absorbance\n0,0.8\n0,abc\n20,0.6\n30,0.5\n40,0.4\n"),
    invalid("Row 3 has a value that isn't a number."),
  );
});

test("four rows are too few", () => {
  assert.throws(
    () => parseReadingsCsv("time_s,absorbance\n0,0.8\n10,0.7\n20,0.6\n30,0.5\n"),
    invalid("The analysis needs at least 5 readings."),
  );
});

test("a BOM, reversed columns, CRLF and blank lines are accepted", () => {
  const text = "\uFEFFabsorbance,time_s\r\n0.8,0\r\n\r\n0.7,10\n0.6,20\n0.5,30\n0.4,40\n\n";
  assert.deepEqual(parseReadingsCsv(text), {
    time_s: [0, 10, 20, 30, 40],
    absorbance: [0.8, 0.7, 0.6, 0.5, 0.4],
  });
});

test("a value that overflows to Infinity is rejected", () => {
  assert.throws(
    () => parseReadingsCsv("time_s,absorbance\n0,1e999\n"),
    invalid("Row 2 has a value that isn't a number."),
  );
});

test("rows whose cells are all empty are skipped like blank lines", () => {
  const text = "time_s,absorbance\n0,0.8\n,\n10,0.7\n20,0.6\n,,\n30,0.5\n40,0.4\n,\n";
  assert.deepEqual(parseReadingsCsv(text), {
    time_s: [0, 10, 20, 30, 40],
    absorbance: [0.8, 0.7, 0.6, 0.5, 0.4],
  });
});

test("row numbers are physical line numbers, blank lines included", () => {
  assert.throws(
    () => parseReadingsCsv("time_s,absorbance\n\n0,0.8\nx,1"),
    invalid("Row 4 has a value that isn't a number."),
  );
  assert.throws(() => parseReadingsCsv("time_s,absorbance\n0,abc"), invalid("Row 2 has a value that isn't a number."));
});

test("the seeded generator is pinned (mulberry32 golden values)", () => {
  assert.deepEqual(SAMPLE_READINGS.absorbance.slice(0, 4), [0.7961, 0.7354, 0.6866, 0.6328]);
});

test("invalid step or duration is rejected, duration 0 gives one point", () => {
  const base = { k: 0.01, a0: 0.8, a_end: 0.05, noise: 0, seed: 1 };
  const message = "The readings step and duration must be positive numbers.";
  for (const bad of [{ step_s: 0 }, { step_s: -5 }, { duration_s: -1 }, { step_s: NaN }, { duration_s: Infinity }]) {
    assert.throws(() => syntheticReadings({ ...base, ...bad }), invalid(message));
  }
  assert.equal(syntheticReadings({ ...base, duration_s: 0 }).time_s.length, 1);
});
