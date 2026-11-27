import assert from "node:assert/strict";
import { test } from "node:test";

import { INITIAL_LOAD, canSaveSettings, settingsEditable, settingsLoad } from "./settings.ts";

test("the settings form starts disabled while the rule loads", () => {
  assert.deepEqual(INITIAL_LOAD, { status: "loading" });
  assert.equal(settingsEditable(INITIAL_LOAD), false);
  assert.equal(canSaveSettings(INITIAL_LOAD, false), false);
});

test("a failed load keeps the form disabled and can't save defaults over an unknown rule", () => {
  const failed = settingsLoad(INITIAL_LOAD, { type: "failed", error: "The service is down." });
  assert.deepEqual(failed, { status: "failed", error: "The service is down." });
  assert.equal(settingsEditable(failed), false);
  assert.equal(canSaveSettings(failed, false), false);
});

test("Try again goes back to loading, and a load that then succeeds enables the form", () => {
  const failed = settingsLoad(INITIAL_LOAD, { type: "failed", error: "x" });
  const retrying = settingsLoad(failed, { type: "retry" });
  assert.deepEqual(retrying, { status: "loading" });
  assert.equal(canSaveSettings(retrying, false), false);
  const loaded = settingsLoad(retrying, { type: "loaded" });
  assert.equal(settingsEditable(loaded), true);
  assert.equal(canSaveSettings(loaded, false), true);
  assert.equal(canSaveSettings(loaded, true), false);
});

test("once loaded, a later failed refresh doesn't take the known rule away", () => {
  const loaded = settingsLoad(INITIAL_LOAD, { type: "loaded" });
  assert.deepEqual(settingsLoad(loaded, { type: "failed", error: "x" }), { status: "loaded" });
});
