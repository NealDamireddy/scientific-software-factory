import assert from "node:assert/strict";
import test from "node:test";
import { formatBytes, replacesShared, scopeLabel, shareable } from "./library-model.ts";

const entry = (over) => ({ id: 1, source_id: "s", scope: "lab:x", revision: 1, kind: "manual", title: "T", origin: "", digest: "d1", bytes: 10, contributed_by: "a", created_at: "", document_id: "library:1", ...over });

test("scopeLabel names who can see an entry", () => {
  assert.equal(scopeLabel("shared"), "Shared with all labs");
  assert.equal(scopeLabel("lab:x"), "This lab only");
});

test("shareable is true only for lab entries without an identical shared copy", () => {
  const lab = entry({});
  assert.equal(shareable(lab, [lab]), true);
  const shared = entry({ id: 2, scope: "shared" });
  assert.equal(shareable(shared, [shared]), false);
  assert.equal(shareable(lab, [lab, shared]), false);
  assert.equal(shareable(lab, [lab, entry({ id: 3, scope: "shared", digest: "d2" })]), true);
});

test("formatBytes uses 1024 base with one decimal below 10 KB", () => {
  assert.equal(formatBytes(812), "812 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(262144), "256 KB");
});

test("replacesShared is true only when a different shared text exists for the same source", () => {
  const lab = entry({});
  assert.equal(replacesShared(lab, [lab]), false);
  assert.equal(replacesShared(lab, [lab, entry({ id: 2, scope: "shared", digest: "d2" })]), true);
  assert.equal(replacesShared(lab, [lab, entry({ id: 2, scope: "shared", digest: "d1" })]), false);
  assert.equal(replacesShared(lab, [lab, entry({ id: 2, scope: "shared", digest: "d2", source_id: "other" })]), false);
  assert.equal(replacesShared(lab, [lab, entry({ id: 2, scope: "lab:y", digest: "d2" })]), false);
});
