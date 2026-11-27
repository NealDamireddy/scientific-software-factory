import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { advance, createDraft, startRun } from "./simulation.ts";
import { buildAgentContext, defaultExtensions } from "./extension-model.ts";
import { deliverReview, recordDelivery, skillVersion } from "./worker-delivery.ts";

const custom = { id: "note", name: "Étalon", whenToUse: "Before starting", instructions: "Trace µM\nagainst the lot." };
const configuration = () => buildAgentContext({
  ...defaultExtensions, skills: ["calibration", custom.id], customSkills: [custom],
  harness: { name: "Private harness", endpoint: "https://private.test" },
});
const start = () => startRun(createDraft("Measure B12", "B12 quantification"), "original", configuration());

function fakeWorker(alter = () => {}) {
  return async (url, options) => {
    assert.equal(url, "/api/experiment-review");
    assert.equal(options.method, "POST");
    const body = JSON.parse(options.body);
    assert.deepEqual(Object.keys(body).sort(), ["briefing", "deliveryId", "skills"]);
    assert.doesNotMatch(options.body, /private.test/);
    assert.deepEqual(body.skills.map((skill) => skill.id), ["calibration", "note"]);
    const receipt = {
      deliveryId: body.deliveryId, receivedAt: "2026-11-27T10:00:00Z",
      review: "Locate the lot record.",
      skills: body.skills.reverse().map(({id, name, whenToUse, instructions, stage}) => ({
        id, name, version: createHash("sha256").update(JSON.stringify([id, name, whenToUse, instructions, stage ?? null])).digest("hex"),
      })),
    };
    alter(receipt);
    return Response.json(receipt);
  };
}

test("delivers exactly the run-start selection, verifies peer versions and preserves the captured snapshot", async () => {
  const run = start().runs[0];
  const receipt = await deliverReview(run.workerDelivery.id, run.agentContext, "localhost", fakeWorker());
  assert.equal(receipt.status, "received");
  assert.equal(receipt.skills[1].version, await skillVersion(custom));
  assert.notEqual(receipt.skills[1].version, await skillVersion({...custom, instructions: "An edit"}));
});

test("rejects conflicting versions, missing skills and receipts for another delivery", async () => {
  const run = start().runs[0];
  for (const change of [
    (r) => { r.skills[0].version = "0".repeat(64); },
    (r) => { r.skills.pop(); },
    (r) => { r.deliveryId = crypto.randomUUID(); },
  ]) {
    const response = await deliverReview(run.workerDelivery.id, run.agentContext, "localhost", fakeWorker(change));
    assert.equal(response.status, "failed");
    assert.match(response.error, /verified/);
  }
});

test("keeps a local receipt with its original run across repeated runs and workspace resets", async () => {
  let experiment = start();
  const first = experiment.runs[0];
  while (experiment.status === "Running") experiment = advance(experiment);
  experiment = startRun(experiment, "repeat", configuration());
  const repeat = experiment.runs[1];
  assert.notEqual(repeat.workerDelivery.id, first.workerDelivery.id);
  const receipt = await deliverReview(first.workerDelivery.id, first.agentContext, "localhost", fakeWorker());
  const [updated] = recordDelivery([experiment], receipt);
  assert.deepEqual(updated.runs[0].workerDelivery, receipt);
  assert.equal(updated.runs[0].outcome, "flagged");
  assert.equal(updated.runs[1], repeat);
  assert.deepEqual(recordDelivery([], receipt), []);
  assert.equal(recordDelivery([updated], {...receipt, status: "failed", error: "stale"})[0], updated);
});

test("does not send browser skill content to a hosted deployment", async () => {
  const run = start().runs[0];
  let calls = 0;
  const response = await deliverReview(run.workerDelivery.id, run.agentContext, "app.example.test", async () => { calls++; });
  assert.equal(calls, 0);
  assert.equal(response.status, "failed");
});
