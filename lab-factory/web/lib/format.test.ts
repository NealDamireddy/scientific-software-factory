import assert from "node:assert/strict";
import { test } from "node:test";

import { plainNumber, sig3 } from "./format.ts";

test("sig3 gives 3 significant figures as plain decimals", () => {
  assert.equal(sig3(0.0085123), "0.00851");
  assert.equal(sig3(0.01), "0.0100");
  assert.equal(sig3(81.5432), "81.5");
  assert.equal(sig3(81.56), "81.6");
  assert.equal(sig3(0.0040512), "0.00405");
  assert.equal(sig3(1234.5), "1230");
  assert.equal(sig3(9.996), "10.0");
  assert.equal(sig3(0.0009996), "0.00100");
  assert.equal(sig3(0), "0");
  assert.equal(sig3(-0), "0");
  assert.equal(sig3(-0.123456), "-0.123");
  assert.equal(sig3(0.000012345), "0.0000123");
  for (const n of [1e-7, 3.21e-6, 12345678]) assert.doesNotMatch(sig3(n), /e/i);
});

test("sig3 never writes exponent notation, however big or small", () => {
  assert.equal(sig3(1e25), "10000000000000000000000000");
  assert.equal(sig3(-1.2345e22), "-12300000000000000000000");
  assert.equal(sig3(1e21), "1000000000000000000000");
  assert.equal(sig3(-0), "0");
  assert.equal(sig3(-1234.5), "-1230");
  assert.equal(sig3(-0.000012345), "-0.0000123");
  assert.equal(sig3(1.5e-150), `0.${"0".repeat(149)}150`);
  for (const n of [Number.MAX_VALUE, -Number.MAX_VALUE, Number.MIN_VALUE, 1e100, -1e-100, 123456789012345680000]) {
    assert.doesNotMatch(sig3(n), /e/i, String(n));
    assert.match(sig3(n), /^-?\d+(\.\d+)?$/, String(n));
  }
});

test("sig3 shows a value that isn't finite in words", () => {
  assert.equal(sig3(Number.NaN), "not a number");
  assert.equal(sig3(Number.POSITIVE_INFINITY), "not a number");
  assert.equal(sig3(Number.NEGATIVE_INFINITY), "not a number");
});

test("plainNumber keeps 4 significant figures and drops trailing zeros", () => {
  assert.equal(plainNumber(0.8012), "0.8012");
  assert.equal(plainNumber(0.05000), "0.05");
  assert.equal(plainNumber(600), "600");
  assert.equal(plainNumber(0.123456789), "0.1235");
  assert.equal(plainNumber(1e-7), "0.0000001");
  assert.equal(plainNumber(0), "0");
});
