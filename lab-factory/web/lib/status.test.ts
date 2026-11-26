import assert from "node:assert/strict";
import { test } from "node:test";

import { createSampleClient } from "./sample/client.ts";
import {
  NO_PROCEDURE, attentionText, errorText, outputLabel, statusLine, statusWord, submissionStatusLine, submissionFailed, submissionSummary, unplacedFailures,
} from "./status.ts";
import type { CheckResult, HistoryEvent, StepView, Submission, WorkOrder, WorkOrderStatus } from "./types.ts";

function order(status: WorkOrderStatus): WorkOrder {
  return { id: "WO-1", experiment_id: "e", kind: "procedure", objective: "o", status, released_submission: null, pins: [] };
}

function submission(number: number, results: CheckResult[], passed = results.every((r) => r.passed)): Submission {
  return { work_order_id: "WO-1", number, artifact: null, artifact_digest: "d", results, passed, submitted_at: "2026-11-26T07:00:00Z" };
}

const ok = (name: string): CheckResult => ({ name, passed: true, detail: "fine" });
const bad = (name: string): CheckResult => ({ name, passed: false, detail: "not fine" });

function event(e: HistoryEvent["event"], actor = "factory", note = "", at = "2026-11-26T07:00:00Z", n: number | null = null): HistoryEvent {
  return { event: e, actor, submission: n, note, at };
}

const BASE: HistoryEvent[] = [event("created"), event("claimed"), event("submitted", "factory", "passed", "2026-11-26T07:00:00Z", 1)];

test("a submission with every check passing", () => {
  assert.equal(submissionSummary(submission(1, [ok("a"), ok("b")])), "Submission 1, all checks passed");
});

test("one failing check is singular", () => {
  assert.equal(submissionSummary(submission(1, [ok("a"), bad("b")])), "Submission 1, 1 check failed");
});

test("several failing checks are plural", () => {
  assert.equal(submissionSummary(submission(3, [bad("a"), ok("b"), bad("c"), bad("d")])), "Submission 3, 3 checks failed");
});

test("a submission that did not pass never reads as all passed, even with no failing results", () => {
  assert.equal(submissionSummary(submission(2, [ok("a")], false)), "Submission 2, checks did not pass");
  assert.equal(submissionSummary(submission(2, [], false)), "Submission 2, checks did not pass");
});

test("failing results win over a passed flag that says otherwise", () => {
  assert.equal(submissionSummary(submission(1, [bad("a")], true)), "Submission 1, 1 check failed");
});

test("in progress is being revised", () => {
  assert.equal(statusLine(order("in_progress"), BASE), "Being revised");
});

test("in review is waiting for sign-off", () => {
  assert.equal(statusLine(order("in_review"), BASE), "Waiting for sign-off");
});

test("released names the approver and the date", () => {
  const history = [...BASE, event("approved", "Dr Rivera", "", "2026-11-26T09:30:00Z", 1)];
  assert.equal(statusLine(order("released"), history), "Signed off by Dr Rivera on 26 Nov 2026");
});

test("released uses the latest approval", () => {
  const history = [
    ...BASE,
    event("approved", "Dr Chen", "", "2026-10-02T09:30:00Z", 1),
    event("approved", "Dr Rivera", "", "2026-11-26T09:30:00Z", 2),
  ];
  assert.equal(statusLine(order("released"), history), "Signed off by Dr Rivera on 26 Nov 2026");
});

test("open after a rejection names who rejected it and why", () => {
  const history = [...BASE, event("rejected", "Dr Rivera", "Use the vial B protocol", "2026-11-26T09:30:00Z", 1)];
  assert.equal(statusLine(order("open"), history), "Rejected by Dr Rivera: Use the vial B protocol");
});

test("open with an older rejection that is no longer the latest event is not started", () => {
  const history = [...BASE, event("rejected", "Dr Rivera", "No", "2026-11-26T09:30:00Z", 1), event("created")];
  assert.equal(statusLine(order("open"), history), "Not started");
});

test("open with no rejection is not started", () => {
  assert.equal(statusLine(order("open"), [event("created")]), "Not started");
  assert.equal(statusLine(order("open"), []), "Not started");
});

test("output labels", () => {
  assert.equal(outputLabel("procedure"), "Procedure");
  assert.equal(outputLabel("run_plan"), "Run plan");
  assert.equal(outputLabel("analysis_app"), "Analysis app");
  assert.equal(outputLabel("simulation"), "Simulation");
});

test("a failing summary is a failure, a passing one is not", () => {
  assert.equal(submissionFailed(submission(1, [ok("a")])), false);
  assert.equal(submissionFailed(submission(1, [bad("a")])), true);
  assert.equal(submissionFailed(submission(1, [ok("a")], false)), true);
});

test("status words, attention text and status lines say a status the same way", () => {
  assert.equal(statusWord("released"), "Signed off");
  assert.equal(statusWord("in_review"), "Waiting for sign-off");
  assert.equal(statusWord("in_progress"), "Being revised");
  assert.equal(statusWord("open"), "Not started");
  assert.equal(statusWord(null), NO_PROCEDURE);
  assert.equal(NO_PROCEDURE, "No procedure yet");
  assert.equal(attentionText("sign_off"), statusWord("in_review"));
  assert.equal(attentionText("signed_off"), statusWord("released"));
  assert.equal(attentionText("rejected"), "Rejected");
  for (const status of ["in_progress", "in_review", "open"] as const) {
    assert.equal(statusLine(order(status), BASE), statusWord(status));
  }
});

test("errorText gives an error's message, or the value as text", () => {
  assert.equal(errorText(new Error("Nope.")), "Nope.");
  assert.equal(errorText("plain"), "plain");
});

const fail = (name: string, detail: string): CheckResult => ({ name, passed: false, detail });

function step(number: number, failures: CheckResult[]): StepView {
  return { number, text: `Step ${number}.`, sources: [], settings: [], unchecked: [], failures };
}

test("the seeded Coomassie procedure has no failure outside its steps", async () => {
  const c = createSampleClient({ now: () => new Date("2026-11-26T12:00:00.000Z") });
  const view = (await c.getWorkspace("coomassie-run-1")).procedure!;
  const shown = view.submissions.find((s) => s.number === view.shown)!;
  assert.ok(shown.results.some((r) => !r.passed), "the seed has a failing check to place");
  assert.deepEqual(unplacedFailures(shown.results, view.steps), []);
});

test("a failure for a step that is not shown is left over", () => {
  const placed = fail("step 1: citations", "no citation");
  const stray = fail("step 3: citations", "no citation");
  const results = [ok("schema"), placed, stray];
  assert.deepEqual(unplacedFailures(results, [step(1, [placed])]), [stray]);
});

test("a failure is placed only when both its name and its detail match", () => {
  const onStep = fail("step 1: wavelength", "750 nm is above the maximum 700 nm");
  const other = fail("step 1: wavelength", "a different detail");
  assert.deepEqual(unplacedFailures([onStep, other], [step(1, [onStep])]), [other]);
});

test("with no steps every failure is left over, and passing checks never are", () => {
  const a = fail("schema", "missing steps");
  const b = fail("step 1: citations", "no citation");
  assert.deepEqual(unplacedFailures([ok("x"), a, b], []), [a, b]);
  assert.deepEqual(unplacedFailures([ok("x")], []), []);
});

test("an earlier submission never inherits another submission's sign-off or rejection", () => {
  const released = { ...order("released"), released_submission: 2 };
  const history = [event("submitted", "factory", "failed", undefined, 1), event("approved", "Olga", "", undefined, 2)];
  assert.equal(submissionStatusLine(released, history, 1, 2), "Superseded by submission 2");
  assert.match(submissionStatusLine(released, history, 2, 2), /^Signed off by Olga/);
  assert.equal(submissionStatusLine(released, history, 3, 3), "Signed off submission: 2");
  assert.equal(submissionStatusLine(order("in_review"), [event("rejected", "Li", "Check the units", undefined, 1)], 1, 2),
    "Rejected by Li: Check the units");
});
