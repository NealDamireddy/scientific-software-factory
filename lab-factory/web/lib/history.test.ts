import assert from "node:assert/strict";
import { test } from "node:test";

import {
  approvalLine, citedSources, diffRows, unreadableLine, latestChoice, pinLabel, shortDigest, submissionOptions, summaryTail, unchangedLabel,
} from "./history.ts";
import type { OrderView, ProcedureStep, Submission, WorkOrder } from "./types.ts";

const order = (id: string): WorkOrder => ({
  id, experiment_id: "e", kind: "procedure", objective: "", status: "in_progress", released_submission: null, pins: [],
});

const sub = (workOrderId: string, number: number, steps: ProcedureStep[], failed = 0): Submission => ({
  work_order_id: workOrderId, number, artifact: { steps }, artifact_digest: "d",
  results: Array.from({ length: Math.max(failed, 1) }, (_, i) => ({ name: `c${i}`, passed: failed === 0, detail: "" })),
  passed: failed === 0, submitted_at: "2026-11-26T10:00:00.000Z",
});

const steps: ProcedureStep[] = [
  { text: "One.", citations: ["a"] },
  { text: "Two.", citations: ["a"] },
  { text: "Three.", citations: [] },
  { text: "Four.", citations: ["a"] },
];

test("summaryTail drops the submission number", () => {
  assert.equal(summaryTail(sub("WO-1", 1, steps, 1)), "1 check failed");
  assert.equal(summaryTail(sub("WO-1", 3, steps)), "all checks passed");
  assert.equal(summaryTail(sub("WO-1", 2, steps, 2)), "2 checks failed");
});

test("submissionOptions lists every order's submissions, newest first", () => {
  const view: OrderView<never> = {
    order: order("WO-3"), submissions: [sub("WO-3", 1, steps, 1), sub("WO-3", 2, steps)], shown: 2, steps: [], history: [],
    earlier: [{ order: order("WO-1"), submissions: [sub("WO-1", 1, steps, 1)], history: [] }],
  };
  assert.deepEqual(submissionOptions(view).map((o) => [o.key, o.label, o.record.order.id]), [
    ["WO-3#2", "WO-3 submission 2, all checks passed", "WO-3"],
    ["WO-3#1", "WO-3 submission 1, 1 check failed", "WO-3"],
    ["WO-1#1", "WO-1 submission 1, 1 check failed", "WO-1"],
  ]);
  assert.deepEqual(latestChoice(view), { workOrderId: "WO-3", number: 2 });
  // Without `earlier` (an older service), the newest order alone is listed.
  assert.deepEqual(submissionOptions({ ...view, earlier: undefined }).map((o) => o.key), ["WO-3#2", "WO-3#1"]);
});

const rowsOf = (result: ReturnType<typeof diffRows>) => {
  assert.equal(result.readable, true, JSON.stringify(result));
  return result.readable ? result.rows : [];
};

test("diffRows marks each change and counts the unchanged steps in one row", () => {
  const after = structuredClone(steps);
  after[2] = { ...after[2], citations: ["b"] };
  assert.deepEqual(diffRows("procedure", sub("WO-1", 1, steps), sub("WO-2", 1, after)), {
    readable: true,
    rows: [
      { change: "changed", mark: "Changed: citations", step: "Step 3", text: "Three.", details: ["Sources: was none; now b"] },
      { change: "unchanged", mark: "3 unchanged steps" },
    ],
  });
});

test("diffRows shows added and removed steps with their own text", () => {
  const after: ProcedureStep[] = [steps[0], { text: "New.", citations: ["a"], amounts: [] }, steps[2], { ...steps[3], text: "Four!" }];
  const rows = rowsOf(diffRows("procedure", sub("WO-1", 1, steps), sub("WO-1", 2, after)));
  assert.deepEqual(rows, [
    { change: "removed", mark: "Removed", step: "Step 2", text: "Two." },
    { change: "added", mark: "Added", step: "Step 2", text: "New." },
    { change: "removed", mark: "Removed", step: "Step 4", text: "Four." },
    { change: "added", mark: "Added", step: "Step 4", text: "Four!" },
    { change: "unchanged", mark: "2 unchanged steps" },
  ]);
});

test("diffRows names a moved, changed step by both numbers and lists every changed field", () => {
  const after: ProcedureStep[] = [{ text: "Zero.", citations: [] }, { ...steps[0], citations: ["b"], amounts: [{ what: "x", value: 1, unit: "mL" }] }];
  const rows = rowsOf(diffRows("procedure", sub("WO-1", 1, [steps[0]]), sub("WO-1", 2, after)));
  assert.deepEqual(rows, [
    { change: "added", mark: "Added", step: "Step 1", text: "Zero." },
    { change: "changed", mark: "Changed: citations, amounts", step: "Step 2, was step 1", text: "One.",
      details: ["Sources: was a; now b", "x 1 mL, added"] },
  ]);
});

test("diffRows reads run plan commands, and an empty step list compares as no steps", () => {
  const plan = (value: number) => ({ instrument_id: "uvvis-1", steps: [{ command: "read_absorbance", settings: [{ parameter: "wavelength", value, unit: "nm" }] }] });
  const a = { ...sub("WO-B12-RP", 1, []), artifact: plan(750) };
  const b = { ...sub("WO-B12-RP", 2, []), artifact: plan(550) };
  assert.deepEqual(rowsOf(diffRows("run_plan", a, b)), [
    { change: "changed", mark: "Changed: settings", step: "Step 1", text: "read_absorbance", details: ["Wavelength 550 nm, was 750 nm"] },
  ]);
  assert.deepEqual(rowsOf(diffRows("run_plan", { ...a, artifact: { instrument_id: "uvvis-1", steps: [] } }, b)), [
    { change: "added", mark: "Added", step: "Step 1", text: "read_absorbance" },
  ]);
  assert.equal(unchangedLabel(1), "1 unchanged step");
});

test("a run-plan instrument change remains visible when every command is identical", () => {
  const steps = [{ command: "read", settings: [] }];
  const make = (id: string) => ({ ...sub("WO-RP", 1, []), artifact: { instrument_id: id, steps } });
  assert.deepEqual(rowsOf(diffRows("run_plan", make("meter-a"), make("meter-b"))), [
    { change: "changed", mark: "Changed: instrument", step: "Run plan", text: "meter-a → meter-b", details: [] },
    { change: "unchanged", mark: "1 unchanged step" },
  ]);
});

test("diffRows refuses to compare a malformed artifact and names the side it couldn't read", () => {
  const good = sub("WO-2", 1, steps);
  const broken = { ...sub("WO-1", 1, []), artifact: "broken" };
  const wrongKind = { ...sub("WO-1", 2, []), artifact: { instrument_id: "uvvis-1", steps: [{ command: "x", settings: [] }] } };
  assert.deepEqual(diffRows("procedure", broken, good), { readable: false, unreadable: [{ workOrderId: "WO-1", number: 1 }] });
  assert.deepEqual(diffRows("procedure", good, wrongKind), { readable: false, unreadable: [{ workOrderId: "WO-1", number: 2 }] });
  assert.deepEqual(diffRows("procedure", broken, wrongKind), {
    readable: false, unreadable: [{ workOrderId: "WO-1", number: 1 }, { workOrderId: "WO-1", number: 2 }],
  });
  assert.equal(unreadableLine({ workOrderId: "WO-1", number: 1 }), "WO-1 submission 1's steps couldn't be read, so they can't be compared.");
});

test("pinLabel names each pin, resolving skill titles and falling back to the id", () => {
  assert.equal(pinLabel({ kind: "skill", id: "procedure-style", revision: 1, digest: "x" }, null), "Skill revision 1");
  const titles = new Map([["procedure-style", "How we write procedures"]]);
  const pin = (kind: "lab" | "project" | "experiment" | "skill", id: string, revision: number) => ({ kind, id, revision, digest: "x" });
  assert.equal(pinLabel(pin("lab", "l", 1), titles), "Lab revision 1");
  assert.equal(pinLabel(pin("project", "p", 1), titles), "Project revision 1");
  assert.equal(pinLabel(pin("experiment", "e", 2), titles), "Experiment revision 2");
  assert.equal(pinLabel(pin("skill", "procedure-style", 1), titles), "Skill How we write procedures revision 1");
  assert.equal(pinLabel(pin("skill", "unknown-skill", 3), titles), "Skill unknown-skill revision 3");
  assert.equal(shortDigest("0123456789abcdef"), "0123456789ab");
});

test("citedSources lists each cited document once, and run steps cite none", () => {
  const a = { id: "a", title: "A" };
  const b = { id: "b", title: "B" };
  assert.deepEqual(citedSources([{ sources: [a] }, { sources: [b, a] }, { sources: [] }]), [a, b]);
  assert.deepEqual(citedSources([{}, {}]), []);
});

test("approvalLine names the released submission from the latest approval", () => {
  const s = { ...sub("WO-1", 2, steps), artifact_digest: "abcdef0123456789" };
  const released = { ...order("WO-1"), status: "released" as const, released_submission: 2 };
  const history = [
    { event: "approved" as const, actor: "Dr Old", submission: 1, note: "", at: "2026-11-01T10:00:00.000Z" },
    { event: "approved" as const, actor: "Dr Rivera", submission: 2, note: "", at: "2026-11-26T10:00:00.000Z" },
  ];
  assert.equal(approvalLine(released, s, history), "Approved by Dr Rivera, submission 2, digest abcdef012345, 26 Nov 2026");
  assert.equal(approvalLine(released, { ...s, number: 1 }, history), null);
  assert.equal(approvalLine(order("WO-1"), s, history), null);
  assert.equal(approvalLine(released, s, []), null);
});

test("citation details use document titles when known, and ids otherwise", () => {
  const before: ProcedureStep[] = [{ text: "Mix.", citations: ["sop-1"] }];
  const after: ProcedureStep[] = [{ text: "Mix.", citations: ["sop-1", "protocol"] }];
  const titles = new Map([["protocol", "reduction-protocol.txt"]]);
  const rows = rowsOf(diffRows("procedure", sub("WO-1", 1, before), sub("WO-2", 1, after), titles));
  assert.deepEqual(rows[0], {
    change: "changed", mark: "Changed: citations", step: "Step 1", text: "Mix.",
    details: ["Sources: was sop-1; now sop-1, reduction-protocol.txt"],
  });
  const cleared = rowsOf(diffRows("procedure", sub("WO-2", 1, after), sub("WO-3", 1, [{ text: "Mix.", citations: [] }]), titles));
  assert.deepEqual(cleared[0].change === "changed" && cleared[0].details, ["Sources: was sop-1, reduction-protocol.txt; now none"]);
});

test("action setting details say what each setting was, and which were added or removed", () => {
  const act = (settings: { parameter: string; value: number; unit: string }[], command = "read_absorbance") =>
    ({ instrument_id: "uvvis-1", command, settings });
  const before: ProcedureStep[] = [{ text: "Read.", citations: [], action: act([
    { parameter: "wavelength", value: 600, unit: "nm" }, { parameter: "integration_time", value: 100, unit: "ms" }]) }];
  const after: ProcedureStep[] = [{ text: "Read.", citations: [], action: act([
    { parameter: "wavelength", value: 595, unit: "nm" }, { parameter: "averages", value: 3, unit: "" }], "scan") }];
  const rows = rowsOf(diffRows("procedure", sub("WO-1", 1, before), sub("WO-1", 2, after)));
  assert.deepEqual(rows[0].change === "changed" && rows[0].details, [
    "Command: was “read_absorbance”; now “scan”",
    "Wavelength 595 nm, was 600 nm",
    "Averages 3, added",
    "Integration time 100 ms, removed",
  ]);
});

test("amount details say what each amount was", () => {
  const before: ProcedureStep[] = [{ text: "Add.", citations: [], amounts: [
    { what: "sodium dithionite", value: 10, unit: "mg" }, { what: "water", value: 5, unit: "mL" }] }];
  const after: ProcedureStep[] = [{ text: "Add.", citations: [], amounts: [
    { what: "sodium dithionite", value: 0.5, unit: "g" }, { what: "water", value: 5, unit: "mL" }] }];
  const rows = rowsOf(diffRows("procedure", sub("WO-1", 1, before), sub("WO-1", 2, after)));
  assert.deepEqual(rows[0].change === "changed" && rows[0].details, ["sodium dithionite 0.5 g, was 10 mg"]);
});

test("a changed run step command or wording says what it was", async () => {
  const { changeDetails } = await import("./history.ts");
  assert.deepEqual(changeDetails("text", { text: "Old.", citations: [] }, { text: "New.", citations: [] }, new Map()), ["was “Old.”"]);
  assert.deepEqual(changeDetails("command", { command: "a", settings: [] }, { command: "b", settings: [] }, new Map()), ["was “a”"]);
});

test("a changed instrument says both the old and the new one", async () => {
  const { changeDetails } = await import("./history.ts");
  const step = (instrument_id: string): ProcedureStep => ({
    text: "Read.", citations: [], action: { instrument_id, command: "read_absorbance", settings: [] },
  });
  assert.deepEqual(changeDetails("action", step("uvvis-1"), step("uvvis-2"), new Map()), ["Instrument: was uvvis-1; now uvvis-2"]);
});
