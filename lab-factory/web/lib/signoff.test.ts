import assert from "node:assert/strict";
import { test } from "node:test";

import { createSampleClient } from "./sample/client.ts";
import { canConfirm, nameChoices, signOffMessage } from "./signoff.ts";

test("confirm needs a name, and a reason to reject; whitespace counts as blank", () => {
  assert.equal(canConfirm("approve", { name: "", reason: "" }), false);
  assert.equal(canConfirm("approve", { name: "  \t", reason: "" }), false);
  assert.equal(canConfirm("approve", { name: "Dr Rivera", reason: "" }), true);
  assert.equal(canConfirm("reject", { name: "Dr Rivera", reason: "" }), false);
  assert.equal(canConfirm("reject", { name: "Dr Rivera", reason: " \n " }), false);
  assert.equal(canConfirm("reject", { name: " ", reason: "Use the vial B protocol" }), false);
  assert.equal(canConfirm("reject", { name: "Dr Rivera", reason: "Use the vial B protocol" }), true);
});

test("nameChoices is the listed names under a listed rule, and null (type a name) otherwise", () => {
  assert.equal(nameChoices({ sign_off: { mode: "anyone" } }), null);
  assert.equal(nameChoices(null), null);
  assert.deepEqual(nameChoices({ sign_off: { mode: "listed", names: ["Dr Rivera", "Sam Okafor"] } }), ["Dr Rivera", "Sam Okafor"]);
});

// The interface offers no path to these refusals (a listed rule gives a select, and the buttons always
// name the latest submission), so the copy the form's alert shows is checked against the client here.
test("signOffMessage shows the client's refusal copy for the rule and for a stale submission", async () => {
  const client = createSampleClient();
  await client.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: ["Dr Rivera"] } });
  const rule = await client.approve("WO-B12", 1, "Sam").then(() => null, (e: unknown) => e);
  assert.equal(signOffMessage(rule), "Sam isn't on this lab's sign-off list.");
  const ruleReject = await client.reject("WO-B12", 1, "Sam", "Too vague").then(() => null, (e: unknown) => e);
  assert.equal(signOffMessage(ruleReject), "Sam isn't on this lab's sign-off list.");
  const stale = await client.approve("WO-B12", 2, "Dr Rivera").then(() => null, (e: unknown) => e);
  assert.equal(signOffMessage(stale), "Submission 2 is not the latest. Review submission 1.");
});

test("signOffMessage falls back to plain words for an error that carries none", () => {
  assert.equal(signOffMessage(new Error("Network down")), "Network down");
  assert.equal(signOffMessage("nope"), "The sign-off didn't go through. Try again.");
  assert.equal(signOffMessage(new Error("")), "The sign-off didn't go through. Try again.");
});
