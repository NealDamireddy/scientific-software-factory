import test from "node:test";
import assert from "node:assert/strict";
import { parseRecordCsv, finiteDecimal } from "./record-csv.ts";
const header = "sample,measurement,value,unit\n";
test("preserves physical source rows, quoted identifiers, BOM and reordered headers", () => {
  assert.deepEqual(
    parseRecordCsv(
      '\uFEFFvalue,unit,sample,measurement\r\n1.2e2,AU,"a,""b""","scan\r\npeak"\r\n\r\n,AU,c,scan',
    ),
    [
      {
        row: 2,
        sample: 'a,"b"',
        measurement: "scan\npeak",
        value: 120,
        unit: "AU",
      },
      { row: 5, sample: "c", measurement: "scan", value: null, unit: "AU" },
    ],
  );
});
test("preserves incomplete records and zero", () => {
  assert.deepEqual(
    parseRecordCsv(header + ",,,\na,b,0,c").map((r) => r.value),
    [null, 0],
  );
});
test("rejects bad columns, ambiguous quotes, and invalid numbers", () => {
  for (const text of [
    "x,y,z,q\nx,y,z,q",
    header + "a,b,12,AU,extra",
    header + "a,b",
    header + 'a,"b,1,AU',
    header + 'a,"b"x,1,AU',
    header + "a,b,NaN,AU",
    header + "a,b,0x12,AU",
    header + "a,b,1e400,AU",
    header,
  ])
    assert.throws(() => parseRecordCsv(text));
  assert.equal(finiteDecimal("-.35"), -0.35);
  assert.equal(finiteDecimal("  "), null);
});
test("bounds file and row count", () => {
  assert.throws(
    () => parseRecordCsv(header + "a,b,1,c\n".repeat(1001)),
    /1,000/,
  );
  assert.throws(() => parseRecordCsv("a".repeat(1024 * 1024 + 1)), /1 MB/);
});
