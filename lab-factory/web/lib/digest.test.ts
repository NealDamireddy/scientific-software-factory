import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { canonicalDigest, canonicalJson, sha256Hex } from "./digest.ts";

function example(name: string): unknown {
  const url = new URL(`../../examples/${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, "utf8"));
}

test("canonicalDigest matches Python for the example lab", async () => {
  assert.equal(
    await canonicalDigest(example("uvvis-lab.json")),
    "dff378a22a9c72069050e3d338702ddd944987fdde5e067e6290bbc7f468b727",
  );
});

test("canonicalDigest matches Python for the example experiment", async () => {
  assert.equal(
    await canonicalDigest(example("b12-experiment.json")),
    "84fa43772c6c04a0b658d7426a1886b19ba3696002da20758d6acb2abbe3afeb",
  );
});

test("canonicalJson sorts keys and escapes non-ASCII", () => {
  assert.equal(canonicalJson({ b: 1, a: "é" }), '{"a":"\\u00e9","b":1}');
});

test("canonicalJson escapes like Python's ensure_ascii", () => {
  assert.equal(canonicalJson("😀"), '"\\ud83d\\ude00"');
  assert.equal(canonicalJson('a"b\\c\n\t\u0001\u007f'), '"a\\"b\\\\c\\n\\t\\u0001\\u007f"');
});

test("canonicalJson formats numbers like Python", () => {
  assert.equal(canonicalJson([400, 278.15, 0.1, -3, 1e-5, 1.5e-7, 1e22, 1.5e300]),
    "[400,278.15,0.1,-3,1e-05,1.5e-07,1e+22,1.5e+300]");
  assert.equal(canonicalJson(0.0001), "0.0001");
  assert.equal(canonicalJson(1234567.5), "1234567.5");
  assert.throws(() => canonicalJson(Number.NaN));
});

test("canonicalJson handles nesting, null, booleans and no whitespace", () => {
  assert.equal(canonicalJson({ z: [true, false, null, { y: 1, x: [] }], a: {} }),
    '{"a":{},"z":[true,false,null,{"x":[],"y":1}]}');
});

test("sha256Hex hashes UTF-8 text", async () => {
  assert.equal(await sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});
