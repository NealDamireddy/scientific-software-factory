import assert from "node:assert/strict";
import { test } from "node:test";

import { diffSteps } from "../diff.ts";
import { ClientError } from "../types.ts";
import type { ActivityItem, ProcedureStep, StepView } from "../types.ts";
import { createSampleClient } from "./client.ts";
import { REFERENCE_CASES } from "./content.ts";
import { proposeOutputs } from "./conversation.ts";

const NOW = new Date("2026-11-26T12:00:00.000Z");
const LAB = "emory-biophys";
const fresh = (options: { delayMs?: number; stepMs?: number } = {}) => createSampleClient({ now: () => NOW, ...options });

const PROPOSAL = "Here’s what I’d build for this experiment. Switch anything off you don’t need, then confirm.";
const BUILT = "Built. Everything passed its checks and is waiting for sign-off.";
const SAMPLE_REPLY = "This is sample data, so the factory can’t act on that here. In the live app it would answer and update the outputs.";
const COOMASSIE_REPLY = "I added reduction-protocol.txt to this experiment and rewrote the procedure. Every check passes, and it’s waiting for sign-off.";

async function rejects(promise: Promise<unknown>, code: string, message?: string): Promise<void> {
  await assert.rejects(promise, (error) => {
    assert.ok(error instanceof ClientError, String(error));
    assert.equal(error.code, code);
    if (message !== undefined) assert.equal(error.message, message);
    return true;
  });
}

const protocol = () => new File(["Add the reducing agent dropwise."], "reduction-protocol.txt", { type: "text/plain" });

async function newExperiment(c: ReturnType<typeof fresh>, description: string, projectId = "coomassie-reduction") {
  const e = await c.createExperiment(projectId, description, ["uvvis-1"]);
  const proposal = (await c.getWorkspace(e.id)).messages[1];
  return { e, proposal };
}

test("proposeOutputs always includes the procedure and keeps a fixed order", () => {
  assert.deepEqual(proposeOutputs("measure the rate of fading"), ["procedure", "analysis_app"]);
  assert.deepEqual(proposeOutputs("simulate it"), ["procedure", "simulation"]);
  assert.deepEqual(proposeOutputs("Wash the glassware"), ["procedure"]);
  assert.deepEqual(proposeOutputs("Predict the curve, then automate the sequence"), ["procedure", "run_plan", "analysis_app", "simulation"]);
  assert.deepEqual(proposeOutputs("Quantify B12 with instrument control"), ["procedure", "run_plan", "analysis_app"]);
});

test("creating an experiment opens the conversation with a proposal", async () => {
  const c = fresh();
  const e = await c.createExperiment("b12-quantification", "  Measure the rate of fading and simulate it ", ["uvvis-1"]);
  const { messages } = await c.getWorkspace(e.id);
  assert.equal(messages.length, 2);
  assert.deepEqual(messages[0], { id: `${e.id}-m1`, from: "person", text: "Measure the rate of fading and simulate it", at: NOW.toISOString() });
  assert.deepEqual(messages[1], {
    id: `${e.id}-m2`, from: "factory", text: PROPOSAL, at: NOW.toISOString(),
    proposal: { outputs: ["procedure", "analysis_app", "simulation"], accepted: null },
  });
});

test("confirmPlan with a procedure plays the activity and builds one passing order", async () => {
  const c = fresh();
  const { e, proposal } = await newExperiment(c, "Wash and read the dye");
  const seen: ActivityItem[] = [];
  const result = await c.confirmPlan(e.id, proposal.id, ["procedure"], (item) => seen.push(item));
  assert.equal(result.length, 1);
  const built = result[0];
  assert.equal(built.from, "factory");
  assert.equal(built.text, BUILT);
  const view = await c.getSubmissionView("WO-2", 1);
  const k = view.submission.results.length;
  assert.equal(k, 15);
  assert.ok(view.submission.results.some((r) => r.name === "step 1: text values"));
  assert.deepEqual(seen.map((a) => [a.label, a.outcome]), [
    ["Read lab context (revision 1)", "done"],
    ["Read project context (revision 1)", "done"],
    ["Used skill: How we write procedures", "info"],
    ["Used skill: Units we report in", "info"],
    ["Wrote procedure", "done"],
    [`Ran ${k} checks: all passed`, "passed"],
  ]);
  assert.ok(!seen.some((a) => a.label.includes("Plotting conventions")));
  assert.deepEqual(built.activity, seen);
  assert.equal(new Set(seen.map((a) => a.id)).size, seen.length);
  assert.deepEqual(built.output_refs, [{ kind: "procedure", work_order_id: "WO-2", summary: "Submission 1, all checks passed" }]);

  const w = await c.getWorkspace(e.id);
  assert.deepEqual(w.messages.map((m) => m.id), [`${e.id}-m1`, `${e.id}-m2`, `${e.id}-m3`]);
  assert.deepEqual(w.messages[1].proposal, { outputs: ["procedure"], accepted: ["procedure"] });
  assert.deepEqual(w.messages[2], built);
  const order = w.procedure!.order;
  assert.equal(order.id, "WO-2");
  assert.equal(order.status, "in_review");
  assert.equal(order.kind, "procedure");
  assert.equal(order.released_submission, null);
  assert.deepEqual(order.pins.map((p) => [p.kind, p.id, p.revision]), [
    ["lab", LAB, 1], ["project", "coomassie-reduction", 1], ["experiment", e.id, 1],
    ["skill", "procedure-style", 1], ["skill", "reporting-units", 1],
  ]);
  assert.equal(order.pins.filter((p) => p.kind === "skill").length, 2);
  assert.equal(order.pins[2].digest, (await c.listRevisions("experiment", e.id))[0].digest);
  assert.equal(order.pins[1].digest, (await c.listRevisions("project", "coomassie-reduction"))[0].digest);
  assert.equal(order.pins[0].digest, (await c.listRevisions("lab", LAB))[0].digest);
  assert.equal(view.submission.passed, true);
  assert.ok(view.submission.results.every((r) => r.passed));
  assert.equal(view.submission.submitted_at, NOW.toISOString());
  assert.match(view.submission.artifact_digest, /^[0-9a-f]{64}$/);
  // Every citation resolves to the lab SOP or a project document.
  const steps = (view.submission.artifact as { steps: ProcedureStep[] }).steps;
  for (const [i, step] of steps.entries()) {
    assert.ok(step.citations.length > 0);
    for (const id of step.citations) assert.ok(["sop-cuvette", "coomassie-dye-prep"].includes(id), id);
    assert.equal((view.steps[i] as StepView).sources.length, step.citations.length);
  }
  assert.ok(steps.some((s) => s.action?.instrument_id === "uvvis-1"));
  assert.deepEqual(w.procedure!.history.map((h) => [h.event, h.actor, h.submission, h.note]), [
    ["created", "factory", null, ""], ["claimed", "factory", null, ""], ["submitted", "factory", 1, "passed"],
  ]);
  assert.equal(w.run_plan, undefined);
  assert.equal(w.analysis_app, undefined);
  assert.equal(w.simulation, undefined);
  assert.deepEqual((await c.needsAttention(LAB, "approver")).map((a) => a.work_order_id), ["WO-B12", "WO-2"]);
});

test("a throwing onActivity callback does not strand the build", async () => {
  const c = fresh();
  const { e, proposal } = await newExperiment(c, "Wash and read the dye");
  const [built] = await c.confirmPlan(e.id, proposal.id, ["procedure"], () => { throw new Error("ui broke"); });
  assert.equal(built.text, BUILT);
  assert.equal(built.activity!.length, 6);
  assert.deepEqual(built.output_refs, [{ kind: "procedure", work_order_id: "WO-2", summary: "Submission 1, all checks passed" }]);
  assert.equal((await c.getWorkspace(e.id)).procedure!.order.id, "WO-2");
});

test("confirmPlan validates its arguments and refuses a second confirmation", async () => {
  const c = fresh();
  const { e, proposal } = await newExperiment(c, "Measure the rate of fading");
  await rejects(c.confirmPlan("nope", proposal.id, ["procedure"]), "not_found");
  await rejects(c.confirmPlan(e.id, "nope", ["procedure"]), "not_found");
  await rejects(c.confirmPlan(e.id, `${e.id}-m1`, ["procedure"]), "invalid");
  await rejects(c.confirmPlan(e.id, proposal.id, []), "invalid");
  await rejects(c.confirmPlan(e.id, proposal.id, ["simulation"]), "invalid");
  await rejects(c.confirmPlan(e.id, proposal.id, ["procedure", "run_plan"]), "invalid");
  assert.equal((await c.getWorkspace(e.id)).messages[1].proposal!.accepted, null);
  await c.confirmPlan(e.id, proposal.id, ["analysis_app"]);
  await rejects(c.confirmPlan(e.id, proposal.id, ["analysis_app"]), "refused", "This plan was already confirmed.");
  await rejects(c.confirmPlan("coomassie-run-1", "coomassie-run-1-m2", ["procedure"]), "refused", "This plan was already confirmed.");
});

test("two overlapping confirmations build once", async () => {
  const c = fresh({ delayMs: 5, stepMs: 2 });
  const { e, proposal } = await newExperiment(c, "Measure the rate of fading");
  const seen: ActivityItem[] = [];
  const results = await Promise.allSettled([
    c.confirmPlan(e.id, proposal.id, ["procedure", "analysis_app"], (a) => seen.push(a)),
    c.confirmPlan(e.id, proposal.id, ["procedure", "analysis_app"], (a) => seen.push(a)),
  ]);
  assert.deepEqual(results.map((r) => r.status).sort(), ["fulfilled", "rejected"]);
  const w = await c.getWorkspace(e.id);
  assert.equal(w.messages.length, 3);
  assert.equal(new Set(seen.map((a) => a.label)).size, seen.length);
  const orders = (await c.needsAttention(LAB, "approver")).filter((a) => a.experiment_id === e.id);
  assert.deepEqual(orders.map((a) => a.work_order_id), ["WO-2"]);
});

test("an analysis app and a simulation are stored per experiment", async () => {
  const c = fresh();
  const { e, proposal } = await newExperiment(c, "Measure the rate of fading and simulate it");
  const seen: ActivityItem[] = [];
  const [built] = await c.confirmPlan(e.id, proposal.id, ["procedure", "analysis_app"], (a) => seen.push(a));
  assert.deepEqual(seen.slice(-2).map((a) => [a.label, a.outcome]), [["Wrote analysis app", "done"], ["Ran 3 reference cases", "info"]]);
  assert.deepEqual(built.output_refs!.map((r) => [r.kind, r.summary]), [
    ["procedure", "Submission 1, all checks passed"], ["analysis_app", "Turns absorbance over time into a rate constant and half-life."],
  ]);
  const w = await c.getWorkspace(e.id);
  assert.ok(w.procedure);
  assert.equal(w.analysis_app!.entry, "analyze");
  assert.deepEqual(w.analysis_app!.reference_cases, REFERENCE_CASES);
  assert.equal(w.simulation, undefined);

  const other = await newExperiment(c, "Simulate the fading");
  const [sim] = await c.confirmPlan(other.e.id, other.proposal.id, ["simulation"]);
  assert.deepEqual(sim.activity!.map((a) => a.label).slice(-1), ["Wrote simulation"]);
  assert.equal(sim.output_refs!.length, 1);
  assert.equal(sim.output_refs![0].kind, "simulation");
  assert.equal(sim.output_refs![0].work_order_id, undefined);
  const ws = await c.getWorkspace(other.e.id);
  assert.equal(ws.simulation!.entry, "simulate");
  assert.equal(ws.procedure, undefined);
});

test("a run plan proposal builds a passing run plan after the procedure", async () => {
  const c = fresh();
  const { e, proposal } = await newExperiment(c, "Automate the absorbance reads", "b12-quantification");
  assert.deepEqual(proposal.proposal!.outputs, ["procedure", "run_plan"]);
  const [built] = await c.confirmPlan(e.id, proposal.id, ["run_plan", "procedure"]);
  assert.deepEqual(built.output_refs, [
    { kind: "procedure", work_order_id: "WO-2", summary: "Submission 1, all checks passed" },
    { kind: "run_plan", work_order_id: "WO-3", summary: "Submission 1, all checks passed" },
  ]);
  const w = await c.getWorkspace(e.id);
  assert.equal(w.run_plan!.order.id, "WO-3");
  assert.equal(w.run_plan!.order.status, "in_review");
  assert.equal(w.run_plan!.submissions[0].passed, true);
  const k = w.run_plan!.submissions[0].results.length;
  const labels = built.activity!.map((a) => a.label);
  assert.deepEqual(labels.slice(-2), ["Wrote run plan", `Ran ${k} checks: all passed`]);
  assert.equal(w.run_plan!.steps[0].instrument_id, "uvvis-1");
  // B12 has no project documents: the procedure cites the lab SOP only.
  const steps = (w.procedure!.submissions[0].artifact as { steps: ProcedureStep[] }).steps;
  assert.ok(steps.every((s) => s.citations.length === 1 && s.citations[0] === "sop-cuvette"));
});

test("an experiment without instruments uses the lab's first, and a new project is pinned at revision 1", async () => {
  const c = fresh();
  const project = await c.createProject(LAB, "Protein folding", "Watch it fold.");
  const e = await c.createExperiment(project.id, "Watch it fold", []);
  const { messages } = await c.getWorkspace(e.id);
  await c.confirmPlan(e.id, messages[1].id, ["procedure"]);
  const w = await c.getWorkspace(e.id);
  const pin = w.procedure!.order.pins.find((p) => p.kind === "project")!;
  assert.deepEqual(pin, { kind: "project", id: project.id, revision: 1, digest: (await c.listRevisions("project", project.id))[0].digest });
  const steps = (w.procedure!.submissions[0].artifact as { steps: ProcedureStep[] }).steps;
  assert.ok(steps.some((s) => s.action?.instrument_id === "uvvis-1"));
});

test("activity items are spaced by stepMs", async () => {
  const c = fresh({ stepMs: 20 });
  const { e, proposal } = await newExperiment(c, "Wash and read the dye");
  const times: number[] = [];
  await c.confirmPlan(e.id, proposal.id, ["procedure"], () => times.push(Date.now()));
  assert.equal(times.length, 6);
  for (let i = 1; i < times.length; i += 1) assert.ok(times[i] - times[i - 1] >= 15, `gap ${i}`);
});

test("attaching a protocol to Coomassie makes revision 2 and a passing WO-2", async () => {
  const c = fresh();
  const wo1Before = await c.getSubmissionView("WO-1", 1);
  const seen: ActivityItem[] = [];
  const result = await c.sendMessage("coomassie-run-1", " Here is the protocol ", [protocol()], (a) => seen.push(a));
  assert.equal(result.length, 2);
  const [person, reply] = result;
  assert.equal(person.from, "person");
  assert.equal(person.text, "Here is the protocol");
  assert.deepEqual(person.attachments, ["reduction-protocol.txt"]);
  assert.equal(reply.text, COOMASSIE_REPLY);
  assert.deepEqual(seen.map((a) => [a.label, a.outcome]), [
    ["Read your attachment", "done"], ["Rewrote procedure", "done"], ["Ran 10 checks: all passed", "passed"],
  ]);
  assert.deepEqual(reply.activity, seen);
  assert.equal(new Set(seen.map((a) => a.id)).size, 3);
  assert.deepEqual(reply.output_refs, [{ kind: "procedure", work_order_id: "WO-2", summary: "Submission 1, all checks passed" }]);

  const revisions = await c.listRevisions("experiment", "coomassie-run-1");
  assert.equal(revisions.length, 2);
  const w = await c.getWorkspace("coomassie-run-1");
  assert.deepEqual(w.experiment.documents, [{
    id: "reduction-protocol-txt", kind: "paper", title: "reduction-protocol.txt",
    source: "Attached in the conversation", text: "Add the reducing agent dropwise.",
  }]);
  assert.deepEqual(w.messages.slice(-2), result);
  const order = w.procedure!.order;
  assert.equal(order.id, "WO-2");
  assert.equal(order.status, "in_review");
  assert.deepEqual(order.pins.find((p) => p.kind === "experiment"), {
    kind: "experiment", id: "coomassie-run-1", revision: 2, digest: revisions[1].digest,
  });
  assert.equal(order.pins.filter((p) => p.kind === "skill").length, 2);
  assert.deepEqual(w.procedure!.history.map((h) => h.event), ["created", "claimed", "submitted"]);
  const sub = w.procedure!.submissions[0];
  assert.equal(sub.results.length, 10);
  assert.equal(sub.passed, true);
  assert.equal((w.procedure!.steps[3] as StepView).sources[0].title, "reduction-protocol.txt");
  assert.deepEqual(w.procedure!.steps[3].failures, []);

  const wo1 = (wo1Before.submission.artifact as { steps: ProcedureStep[] }).steps;
  const wo2 = (sub.artifact as { steps: ProcedureStep[] }).steps;
  assert.deepEqual(wo2[3].citations, ["reduction-protocol-txt"]);
  const changes = diffSteps(wo1, wo2);
  assert.deepEqual(changes.filter((x) => x.change !== "same"), [{ change: "changed", before: 3, after: 3, fields: ["citations"] }]);
  assert.equal(changes.filter((x) => x.change === "same").length, 4);

  // WO-1 is untouched, and the workspace lists it as the earlier procedure.
  assert.deepEqual(await c.getSubmissionView("WO-1", 1), wo1Before);
  const earlier = w.procedure!.earlier!;
  assert.deepEqual(earlier.map((e) => [e.order.id, e.order.status, e.submissions.length]), [["WO-1", "in_progress", 1]]);
  assert.deepEqual(earlier[0].submissions[0], wo1Before.submission);
  assert.deepEqual(earlier[0].history.map((h) => h.event), ["created", "claimed", "submitted"]);
  assert.equal(w.procedure!.order.id === "WO-1", false);
  assert.deepEqual((await c.needsAttention(LAB, "approver")).map((a) => [a.work_order_id, a.title]), [
    ["WO-B12", "Vitamin B12 absorbance"], ["WO-2", "Reducing Coomassie blue"],
  ]);
  assert.equal((await c.approve("WO-2", 1, "Dr Rivera")).status, "released");

  // A second attachment takes the generic path: no new order.
  const [, again] = await c.sendMessage("coomassie-run-1", "", [new File(["More notes."], "notes.txt")]);
  assert.equal(again.text, "I added notes.txt to this experiment. Tell me what to change and I’ll rebuild.");
  assert.equal(again.activity, undefined);
  assert.equal((await c.listRevisions("experiment", "coomassie-run-1")).length, 3);
  assert.equal((await c.getWorkspace("coomassie-run-1")).procedure!.order.id, "WO-2");
});

test("two overlapping Coomassie attachments rewrite once", async () => {
  const c = fresh({ stepMs: 2, delayMs: 5 });
  const results = await Promise.all([
    c.sendMessage("coomassie-run-1", "Here is the protocol", [protocol()]),
    c.sendMessage("coomassie-run-1", "Here is the protocol", [protocol()]),
  ]);
  assert.deepEqual((await c.needsAttention(LAB, "approver")).map((a) => a.work_order_id), ["WO-B12", "WO-2"]);
  assert.equal((await c.listRevisions("experiment", "coomassie-run-1")).length, 2);
  assert.equal(results.filter(([, reply]) => reply.text === COOMASSIE_REPLY).length, 1);
});

test("other attachments are added as documents and named in the reply", async () => {
  const c = fresh();
  const [person, reply] = await c.sendMessage("b12-vial-a", "Two files", [
    new File(["First."], "a.txt"), new File(["   "], "b.txt"),
  ]);
  assert.deepEqual(person.attachments, ["a.txt", "b.txt"]);
  assert.equal(reply.text, "I added a.txt and b.txt to this experiment. Tell me what to change and I’ll rebuild.");
  const w = await c.getWorkspace("b12-vial-a");
  assert.deepEqual(w.experiment.documents.map((d) => [d.id, d.kind, d.title, d.text]), [
    ["b12-protocol", "sop", "Vial A protocol", "Use the labeled reference solution in vial A."],
    ["a-txt", "paper", "a.txt", "First."],
    ["b-txt", "paper", "b.txt", "(empty file)"],
  ]);
  const [, three] = await c.sendMessage("b12-vial-a", "", [
    new File(["x".repeat(25_000)], "long.txt"), new File(["y"], "c.txt"), new File(["z"], "d.txt"),
  ]);
  assert.equal(three.text, "I added long.txt, c.txt and d.txt to this experiment. Tell me what to change and I’ll rebuild.");
  const long = (await c.getWorkspace("b12-vial-a")).experiment.documents.find((d) => d.title === "long.txt")!;
  assert.equal(long.text.length, 20_000);
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.order.id, "WO-B12");
});

test("a text-only message gets the fixed sample reply", async () => {
  const c = fresh();
  const result = await c.sendMessage("coomassie-run-1", "hello", []);
  assert.deepEqual(result.map((m) => [m.from, m.text]), [["person", "hello"], ["factory", SAMPLE_REPLY]]);
  assert.equal(result[0].attachments, undefined);
  const w = await c.getWorkspace("coomassie-run-1");
  assert.equal(w.messages.length, 5);
  assert.equal(new Set(w.messages.map((m) => m.id)).size, 5);
  assert.equal(w.procedure!.order.id, "WO-1");
  // Results are copies.
  result[1].text = "changed";
  assert.equal((await c.getWorkspace("coomassie-run-1")).messages[4].text, SAMPLE_REPLY);
});

test("a blank message is invalid and an unknown experiment is not found", async () => {
  const c = fresh();
  await rejects(c.sendMessage("coomassie-run-1", "   \n", []), "invalid");
  await rejects(c.sendMessage("nope", "hello", []), "not_found");
  assert.equal((await c.getWorkspace("coomassie-run-1")).messages.length, 3);
});
