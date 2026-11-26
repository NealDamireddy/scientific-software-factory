import assert from "node:assert/strict";
import { test } from "node:test";

import { tokenizePython } from "./python-tokens.ts";

const kinds = (code: string) => tokenizePython(code).filter((t) => t.kind !== "text").map((t) => [t.kind, t.text]);

test("the tokens put the code back together exactly", () => {
  const code = 'import math\n\ndef f(x):  # a "comment"\n    return f"{x}" if x else None\n';
  assert.equal(tokenizePython(code).map((t) => t.text).join(""), code);
});

test("keywords are whole words only", () => {
  assert.deepEqual(kinds("for x in range(3):\n    pass"), [["keyword", "for"], ["keyword", "in"], ["keyword", "pass"]]);
  assert.deepEqual(kinds("format = fork + iffy + True"), [["keyword", "True"]]);
  assert.deepEqual(kinds("lambda_ = _if"), []);
});

test("strings and comments hide what is inside them", () => {
  assert.deepEqual(kinds("x = 'if # not a comment'  # if not a keyword"), [
    ["string", "'if # not a comment'"], ["comment", "# if not a keyword"],
  ]);
  assert.deepEqual(kinds('s = "a \\" b" + f"{k} mM"'), [["string", '"a \\" b"'], ["string", 'f"{k} mM"']]);
  assert.deepEqual(kinds('"""Doc\nwith "quotes" and def"""\nreturn'), [
    ["string", '"""Doc\nwith "quotes" and def"""'], ["keyword", "return"],
  ]);
});

test("an unterminated string runs to the end of its line, and a triple-quoted one to the end", () => {
  assert.deepEqual(kinds("x = 'open\nif"), [["string", "'open"], ["keyword", "if"]]);
  assert.deepEqual(kinds("x = '''open\nif"), [["string", "'''open\nif"]]);
});
