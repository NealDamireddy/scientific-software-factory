import assert from "node:assert/strict";
import { test } from "node:test";

import { canonicalDigest } from "../digest.ts";
import { ClientError } from "../types.ts";
import type { Submission } from "../types.ts";
import { createSampleClient } from "./client.ts";
import * as records from "./records.ts";
import { slugify, uniqueSlug } from "./records.ts";
import { createSeed } from "./seed.ts";

const NOW = new Date("2026-11-26T12:00:00.000Z");
const fresh = () => createSampleClient({ now: () => NOW });

async function rejects(promise: Promise<unknown>, code: string, message?: string): Promise<void> {
  await assert.rejects(promise, (error) => {
    assert.ok(error instanceof ClientError, String(error));
    assert.equal(error.code, code);
    if (message !== undefined) assert.equal(error.message, message);
    return true;
  });
}

test("slug helpers de-duplicate with -2, -3", () => {
  assert.equal(slugify("  Hello, World! "), "hello-world");
  assert.equal(slugify("!!!", "item"), "item");
  assert.equal(uniqueSlug("Hello", ["hello"]), "hello-2");
  assert.equal(uniqueSlug("Hello", ["hello", "hello-2"]), "hello-3");
  assert.equal(uniqueSlug("Hello", []), "hello");
});

test("lookups return records and throw not_found for unknown ids", async () => {
  const c = fresh();
  assert.equal((await c.getLab("emory-biophys")).name, "Emory Biophysics");
  await rejects(c.getLab("nope"), "not_found");
  const projects = await c.listProjects("emory-biophys");
  assert.deepEqual(projects.map((p) => [p.id, p.experiments.map((e) => e.id)]), [
    ["coomassie-reduction", ["coomassie-run-1"]], ["b12-quantification", ["b12-vial-a"]],
  ]);
  assert.deepEqual(projects[0].experiments[0], { id: "coomassie-run-1", title: "Reducing Coomassie blue" });
  await rejects(c.listProjects("nope"), "not_found");
  const project = await c.getProject("coomassie-reduction");
  assert.equal(project.experiments[0].goal.startsWith("Reduce the central carbon"), true);
  await rejects(c.getProject("nope"), "not_found");
  await rejects(c.getWorkspace("nope"), "not_found");
  await rejects(c.getSubmissionView("nope", 1), "not_found");
  await rejects(c.getSubmissionView("WO-1", 2), "not_found");
  await rejects(c.listRevisions("project", "nope"), "not_found");
  await rejects(c.getSettings("nope"), "not_found");
  await rejects(c.needsAttention("nope", "approver"), "not_found");
  await rejects(c.search("nope", "x"), "not_found");
  await rejects(c.addDocument({ kind: "project", id: "nope" }, { title: "T", kind: "note", text: "x" }), "not_found");
});

test("getWorkspace and getSubmissionView return the stored orders and views", async () => {
  const c = fresh();
  const w = await c.getWorkspace("coomassie-run-1");
  assert.equal(w.project.id, "coomassie-reduction");
  assert.equal(w.messages.length, 3);
  assert.equal(w.procedure?.order.id, "WO-1");
  assert.equal(w.procedure?.shown, 1);
  assert.equal(w.procedure?.steps.length, 5);
  assert.equal(w.procedure?.submissions.length, 1);
  assert.deepEqual(w.procedure?.history.map((h) => h.event), ["created", "claimed", "submitted"]);
  assert.equal(w.run_plan, undefined);
  assert.ok(w.analysis_app && w.simulation);
  const b = await c.getWorkspace("b12-vial-a");
  assert.equal(b.procedure?.order.id, "WO-B12");
  assert.equal(b.run_plan?.order.id, "WO-B12-RP");
  assert.equal(b.analysis_app, undefined);
  assert.equal(b.simulation, undefined);
  const view = await c.getSubmissionView("WO-B12-RP", 1);
  assert.equal(view.submission.number, 1);
  assert.equal(view.steps[0].failures.length, 1);
});

test("the workspace shows the newest order of each kind with every submission", async () => {
  const state = await createSeed(NOW);
  const ctx = { state, now: () => NOW };
  const older = state.orders.find((o) => o.id === "WO-B12")!;
  state.orders.push({ ...structuredClone(older), id: "WO-B12-2" });
  state.submissions.push({ ...structuredClone(state.submissions.find((x) => x.work_order_id === "WO-B12")!), work_order_id: "WO-B12-2" });
  state.submissions.push({ ...structuredClone(state.submissions.find((x) => x.work_order_id === "WO-B12")!), work_order_id: "WO-B12-2", number: 2 });
  state.views["WO-B12-2#2"] = [];
  state.history["WO-B12-2"] = [{ event: "created", actor: "factory", submission: null, note: "", at: NOW.toISOString() }];
  const w = records.getWorkspace(ctx, "b12-vial-a");
  assert.equal(w.procedure?.order.id, "WO-B12-2");
  assert.equal(w.procedure?.shown, 2);
  assert.equal(w.procedure?.submissions.length, 2);
  assert.deepEqual(w.procedure?.steps, []);
  assert.equal(w.procedure?.history.length, 1);
  assert.equal(w.run_plan?.order.id, "WO-B12-RP");
});

test("addDocument adds a revision, dedupes identical content and slugs colliding titles", async () => {
  const c = fresh();
  const doc = { title: "Buffer recipe", kind: "note" as const, text: "Use 50 mM phosphate." };
  const target = { kind: "project" as const, id: "b12-quantification" };
  const first = await c.addDocument(target, doc);
  assert.equal(first.number, 2);
  assert.equal(first.note, "Added Buffer recipe");
  assert.equal(first.at, NOW.toISOString());
  const project = await c.getProject("b12-quantification");
  assert.deepEqual(project.documents, [{ id: "buffer-recipe", kind: "note", title: "Buffer recipe", source: "Added in Lab Factory", text: doc.text }]);
  const { experiments: _e, ...record } = project;
  assert.equal(first.digest, await canonicalDigest(record));
  assert.deepEqual(await c.addDocument(target, doc), first);
  assert.equal((await c.listRevisions("project", "b12-quantification")).length, 2);
  const second = await c.addDocument(target, { ...doc, text: "Different text." });
  assert.equal(second.number, 3);
  const after = await c.getProject("b12-quantification");
  assert.deepEqual(after.documents.map((d) => d.id), ["buffer-recipe", "buffer-recipe-2"]);
  const collides = await c.addDocument({ kind: "experiment", id: "coomassie-run-1" }, { title: "SOP cuvette", kind: "sop", text: "Mine." });
  assert.equal(collides.number, 2);
  const w = await c.getWorkspace("coomassie-run-1");
  assert.deepEqual(w.experiment.documents.map((d) => d.id), ["sop-cuvette-2"]);
  assert.equal(collides.digest, await canonicalDigest({
    id: w.experiment.id, lab_id: w.experiment.lab_id, title: w.experiment.title, goal: w.experiment.goal,
    instrument_ids: w.experiment.instrument_ids, documents: w.experiment.documents,
  }));
  // A new id never collides with a document in the lab, project or a sibling experiment.
  const lab = await c.addDocument({ kind: "project", id: "coomassie-reduction" }, { title: "SOP cuvette", kind: "sop", text: "Other." });
  assert.equal(lab.number, 2);
  assert.ok((await c.getProject("coomassie-reduction")).documents.some((d) => d.id === "sop-cuvette-3"));
});

test("addDocument rejects blank titles and text", async () => {
  const c = fresh();
  const target = { kind: "project" as const, id: "b12-quantification" };
  await rejects(c.addDocument(target, { title: "  ", kind: "note", text: "x" }), "invalid");
  await rejects(c.addDocument(target, { title: "T", kind: "note", text: " \n" }), "invalid");
});

test("overlapping addDocument calls with the same content make one revision", async () => {
  const c = fresh();
  const target = { kind: "project" as const, id: "b12-quantification" };
  const doc = { title: "Same", kind: "note" as const, text: "same" };
  const [a, b] = await Promise.all([c.addDocument(target, doc), c.addDocument(target, doc)]);
  assert.deepEqual(a, b);
  assert.equal((await c.listRevisions("project", "b12-quantification")).length, 2);
});

test("search orders projects, experiments, documents, instruments", async () => {
  const c = fresh();
  assert.deepEqual(await c.search("emory-biophys", "   "), []);
  const cuv = await c.search("emory-biophys", "cuv");
  assert.deepEqual(cuv, [{ kind: "document", id: "sop-cuvette", title: "Cuvette handling", href: "#/lab?doc=sop-cuvette" }]);
  const coom = await c.search("emory-biophys", "COOM");
  assert.deepEqual(coom.map((h) => [h.kind, h.id, h.href]), [
    ["project", "coomassie-reduction", "#/projects/coomassie-reduction"],
    ["experiment", "coomassie-run-1", "#/projects/coomassie-reduction/experiments/coomassie-run-1"],
    ["document", "coomassie-dye-prep", "#/projects/coomassie-reduction?doc=coomassie-dye-prep"],
  ]);
  const b12 = await c.search("emory-biophys", "b12");
  assert.deepEqual(b12.map((h) => h.href), [
    "#/projects/b12-quantification",
    "#/projects/b12-quantification/experiments/b12-vial-a",
    "#/projects/b12-quantification/experiments/b12-vial-a?doc=b12-protocol",
  ]);
  const inst = await c.search("emory-biophys", "spectro");
  assert.deepEqual(inst, [{ kind: "instrument", id: "uvvis-1", title: "UV-visible spectrophotometer", href: "#/lab" }]);
  const many = fresh();
  for (let i = 0; i < 25; i += 1) {
    await many.addDocument({ kind: "project", id: "b12-quantification" }, { title: `Note ${i}`, kind: "note", text: `t${i}` });
  }
  assert.equal((await many.search("emory-biophys", "note")).length, 20);
});

test("approving under anyone releases the order, and a second approve is refused", async () => {
  const c = fresh();
  const order = await c.approve("WO-B12", 1, "  Dr Rivera ");
  assert.equal(order.status, "released");
  assert.equal(order.released_submission, 1);
  const w = await c.getWorkspace("b12-vial-a");
  const last = w.procedure!.history.at(-1)!;
  const sub = w.procedure!.submissions[0];
  assert.deepEqual(last, { event: "approved", actor: "Dr Rivera", submission: 1, note: sub.artifact_digest, at: NOW.toISOString() });
  await rejects(c.approve("WO-B12", 1, "Dr Rivera"), "refused", "This submission isn't waiting for sign-off.");
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.history.filter((h) => h.event === "approved").length, 1);
});

test("overlapping approvals produce one outcome", async () => {
  const c = createSampleClient({ now: () => NOW, delayMs: 5 });
  const results = await Promise.allSettled([c.approve("WO-B12", 1, "Sam"), c.approve("WO-B12", 1, "Sam")]);
  assert.deepEqual(results.map((r) => r.status).sort(), ["fulfilled", "rejected"]);
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.history.filter((h) => h.event === "approved").length, 1);
});

test("approve and reject check in order: order, name, reason, state, rule", async () => {
  const c = fresh();
  await rejects(c.approve("nope", 1, ""), "not_found");
  await rejects(c.reject("nope", 1, "", ""), "not_found");
  await rejects(c.approve("WO-B12", 1, "  "), "invalid");
  await rejects(c.reject("WO-B12", 1, "  ", "reason"), "invalid");
  await rejects(c.reject("WO-B12", 1, "Sam", "  "), "invalid");
  await rejects(c.approve("WO-1", 1, "Sam"), "refused", "This submission isn't waiting for sign-off.");
  await rejects(c.reject("WO-1", 1, "Sam", "why"), "refused", "This submission isn't waiting for sign-off.");
  await rejects(c.approve("WO-B12", 2, "Sam"), "refused", "Submission 2 is not the latest. Review submission 1.");
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.order.status, "in_review");
});

test("a newer submission makes an older one stale", async () => {
  const state = await createSeed(NOW);
  const ctx = { state, now: () => NOW };
  const first = state.submissions.find((s) => s.work_order_id === "WO-B12")!;
  const second: Submission = { ...structuredClone(first), number: 2 };
  state.submissions.push(second);
  state.views["WO-B12#2"] = structuredClone(state.views["WO-B12#1"]);
  const stale = "Submission 1 is not the latest. Review submission 2.";
  assert.throws(() => records.approve(ctx, "WO-B12", 1, "Sam"), { message: stale });
  assert.throws(() => records.reject(ctx, "WO-B12", 1, "Sam", "no"), { message: stale });
  const w = records.getWorkspace(ctx, "b12-vial-a");
  assert.equal(w.procedure!.shown, 2);
  assert.equal(w.procedure!.submissions.length, 2);
  assert.equal(w.procedure!.steps.length, 3);
  assert.equal(records.approve(ctx, "WO-B12", 2, "Sam").released_submission, 2);
});

test("a listed sign-off rule applies, case-insensitively after trimming", async () => {
  const c = fresh();
  const saved = await c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: ["Dr Rivera"] } });
  assert.deepEqual(saved, { sign_off: { mode: "listed", names: ["Dr Rivera"] } });
  await rejects(c.approve("WO-B12", 1, "Sam"), "refused", "Sam isn't on this lab's sign-off list.");
  await rejects(c.reject("WO-B12", 1, "Sam", "no"), "refused", "Sam isn't on this lab's sign-off list.");
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.order.status, "in_review");
  const order = await c.approve("WO-B12", 1, "dr rivera ");
  assert.equal(order.status, "released");
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.history.at(-1)!.actor, "dr rivera");
});

test("rejecting reopens the order, replies in the conversation and shows for the researcher", async () => {
  const c = fresh();
  assert.deepEqual((await c.needsAttention("emory-biophys", "approver")).map((a) => [a.kind, a.work_order_id, a.experiment_id, a.project_id, a.title]), [
    ["sign_off", "WO-B12", "b12-vial-a", "b12-quantification", "Vitamin B12 absorbance"],
  ]);
  assert.deepEqual(await c.needsAttention("emory-biophys", "researcher"), []);
  const order = await c.reject("WO-B12", 1, " Sam ", "  Cite the protocol.  ");
  assert.equal(order.status, "open");
  assert.equal(order.released_submission, null);
  const w = await c.getWorkspace("b12-vial-a");
  assert.deepEqual(w.procedure!.history.at(-1), { event: "rejected", actor: "Sam", submission: 1, note: "Cite the protocol.", at: NOW.toISOString() });
  const last = w.messages.at(-1)!;
  assert.equal(last.from, "factory");
  assert.equal(last.text, "Thanks. I’ll revise this to address: Cite the protocol.");
  assert.equal(new Set(w.messages.map((m) => m.id)).size, w.messages.length);
  assert.deepEqual(await c.needsAttention("emory-biophys", "approver"), []);
  assert.deepEqual((await c.needsAttention("emory-biophys", "researcher")).map((a) => [a.kind, a.work_order_id]), [["rejected", "WO-B12"]]);
  await rejects(c.reject("WO-B12", 1, "Sam", "again"), "refused", "This submission isn't waiting for sign-off.");
});

test("a released order shows as signed_off for the researcher", async () => {
  const c = fresh();
  await c.approve("WO-B12", 1, "Sam");
  assert.deepEqual((await c.needsAttention("emory-biophys", "researcher")).map((a) => [a.kind, a.work_order_id]), [["signed_off", "WO-B12"]]);
});

test("updateSettings validates, trims and de-duplicates names", async () => {
  const c = fresh();
  assert.deepEqual(await c.getSettings("emory-biophys"), { sign_off: { mode: "anyone" } });
  await rejects(c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: [] } }), "invalid");
  await rejects(c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: ["  ", ""] } }), "invalid");
  const saved = await c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: [" Ana ", "Ben", "Ana", " "] } });
  assert.deepEqual(saved, { sign_off: { mode: "listed", names: ["Ana", "Ben"] } });
  assert.deepEqual(await c.getSettings("emory-biophys"), saved);
  assert.deepEqual(await c.updateSettings("emory-biophys", { sign_off: { mode: "anyone" } }), { sign_off: { mode: "anyone" } });
});

test("createProject validates, slugs with a counter and starts at revision 1", async () => {
  const c = fresh();
  await rejects(c.createProject("emory-biophys", " ", "goal"), "invalid");
  await rejects(c.createProject("emory-biophys", "Title", " "), "invalid");
  await rejects(c.createProject("nope", "Title", "goal"), "not_found");
  const p = await c.createProject("emory-biophys", " Protein folding ", "Watch it fold.");
  assert.deepEqual(p, { id: "protein-folding", lab_id: "emory-biophys", title: "Protein folding", goals: "Watch it fold.", documents: [] });
  const q = await c.createProject("emory-biophys", "Protein folding", "Again.");
  assert.equal(q.id, "protein-folding-2");
  const revs = await c.listRevisions("project", "protein-folding");
  assert.deepEqual(revs, [{ number: 1, digest: await canonicalDigest(p), at: NOW.toISOString(), note: "Created" }]);
  assert.equal((await c.listProjects("emory-biophys")).length, 4);
});

test("createExperiment creates revision 1 and an empty conversation", async () => {
  const c = fresh();
  await rejects(c.createExperiment("nope", "Do it", ["uvvis-1"]), "not_found");
  await rejects(c.createExperiment("b12-quantification", "   ", ["uvvis-1"]), "invalid");
  await rejects(c.createExperiment("b12-quantification", "Do it", ["ghost"]), "invalid");
  const long = "Measure how quickly the blue absorbance of the dye fades after we add the reducing agent";
  const e = await c.createExperiment("b12-quantification", long, ["uvvis-1"]);
  assert.equal(e.title, "Measure how quickly the blue absorbance of the dye fades");
  assert.ok(e.title.length <= 60);
  assert.equal(e.goal, long);
  assert.equal(e.id, "measure-how-quickly-the-blue-absorbance-of-the-dye-fades");
  assert.equal(e.project_id, "b12-quantification");
  assert.equal(e.lab_id, "emory-biophys");
  assert.deepEqual(e.instrument_ids, ["uvvis-1"]);
  assert.deepEqual(e.documents, []);
  const { project_id: _p, ...record } = e;
  assert.deepEqual(await c.listRevisions("experiment", e.id), [{ number: 1, digest: await canonicalDigest(record), at: NOW.toISOString(), note: "Created" }]);
  assert.deepEqual((await c.getWorkspace(e.id)).messages, []);
  const again = await c.createExperiment("b12-quantification", long, []);
  assert.equal(again.id, `${e.id}-2`);
  const short = await c.createExperiment("b12-quantification", "Short one", ["uvvis-1"]);
  assert.equal(short.title, "Short one");
  const noSpace = await c.createExperiment("b12-quantification", "x".repeat(80), ["uvvis-1"]);
  assert.equal(noSpace.title, "x".repeat(60));
});

test("results are deep copies of the store", async () => {
  const c = fresh();
  const lab = await c.getLab("emory-biophys");
  lab.instruments[0].parameters[0].maximum = 1;
  lab.documents.length = 0;
  assert.equal((await c.getLab("emory-biophys")).instruments[0].parameters[0].maximum, 700);
  const w = await c.getWorkspace("coomassie-run-1");
  w.messages.length = 0;
  w.procedure!.steps[0].text = "changed";
  w.procedure!.submissions[0].results.length = 0;
  w.analysis_app!.reference_cases.length = 0;
  w.experiment.title = "changed";
  const again = await c.getWorkspace("coomassie-run-1");
  assert.equal(again.messages.length, 3);
  assert.notEqual(again.procedure!.steps[0].text, "changed");
  assert.equal(again.procedure!.submissions[0].results.length, 10);
  assert.equal(again.analysis_app!.reference_cases.length, 3);
  const projects = await c.listProjects("emory-biophys");
  projects[0].title = "changed";
  assert.equal((await c.listProjects("emory-biophys"))[0].title, "Coomassie reduction");
  const revs = await c.listRevisions("lab", "emory-biophys");
  revs[0].note = "changed";
  assert.equal((await c.listRevisions("lab", "emory-biophys"))[0].note, "Created");
  const settings = await c.getSettings("emory-biophys");
  settings.sign_off = { mode: "listed", names: ["x"] };
  assert.deepEqual(await c.getSettings("emory-biophys"), { sign_off: { mode: "anyone" } });
  const view = await c.getSubmissionView("WO-1", 1);
  view.steps.length = 0;
  assert.equal((await c.getSubmissionView("WO-1", 1)).steps.length, 5);
});

test("reset restores the seed", async () => {
  const c = fresh();
  await c.approve("WO-B12", 1, "Sam");
  await c.createProject("emory-biophys", "Extra", "goal");
  await c.updateSettings("emory-biophys", { sign_off: { mode: "listed", names: ["Ana"] } });
  await c.reset();
  assert.equal((await c.getWorkspace("b12-vial-a")).procedure!.order.status, "in_review");
  assert.equal((await c.listProjects("emory-biophys")).length, 2);
  assert.deepEqual(await c.getSettings("emory-biophys"), { sign_off: { mode: "anyone" } });
});

test("concurrent first calls seed once, and delayMs is awaited", async () => {
  let calls = 0;
  const c = createSampleClient({ now: () => { calls += 1; return NOW; } });
  await Promise.all([c.getLab("emory-biophys"), c.getLab("emory-biophys"), c.listProjects("emory-biophys")]);
  assert.equal(calls, 1);
  const slow = createSampleClient({ now: () => NOW, delayMs: 30 });
  const started = Date.now();
  await slow.getLab("emory-biophys");
  assert.ok(Date.now() - started >= 25);
});

test("methods that later tasks add refuse for now", async () => {
  const c = fresh();
  await rejects(c.sendMessage("coomassie-run-1", "hi", []), "refused", "Not available yet.");
  await rejects(c.listSkills("emory-biophys"), "refused", "Not available yet.");
  await rejects(c.getAgentSetup("emory-biophys"), "refused", "Not available yet.");
});
