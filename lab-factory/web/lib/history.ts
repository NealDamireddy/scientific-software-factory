// Submission history for an output: every submission across the experiment's orders of one kind,
// and the rows a step comparison shows. Pure, so it runs under node --test.
import { artifactSteps } from "./artifact.ts";
import { diffSteps } from "./diff.ts";
import type { StepChange } from "./diff.ts";
import { formatDate, submissionSummary } from "./status.ts";
import type { HistoryEvent, OrderView, Pin, ProcedureStep, RunStep, Submission, WorkOrder } from "./types.ts";

export type SubmissionChoice = { workOrderId: string; number: number };
export type OrderRecord = { order: WorkOrder; submissions: Submission[]; history: HistoryEvent[] };
export type SubmissionOption = {
  /** `{order id}#{n}`, unique across the list. */
  key: string;
  label: string;
  submission: Submission;
  record: OrderRecord;
};

export function choiceKey(choice: SubmissionChoice): string {
  return `${choice.workOrderId}#${choice.number}`;
}

/** The newest order first, then the earlier ones as the view lists them (newest first). */
export function orderRecords<S>(view: OrderView<S>): OrderRecord[] {
  return [{ order: view.order, submissions: view.submissions, history: view.history }, ...(view.earlier ?? [])];
}

/** `all checks passed` from `Submission 1, all checks passed`: the summary without its submission number. */
export function summaryTail(submission: Submission): string {
  const summary = submissionSummary(submission);
  const comma = summary.indexOf(", ");
  return comma === -1 ? summary : summary.slice(comma + 2);
}

/** Every submission of every order, newest order first and newest submission first within it. */
export function submissionOptions<S>(view: OrderView<S>): SubmissionOption[] {
  return orderRecords(view).flatMap((record) =>
    [...record.submissions].sort((a, b) => b.number - a.number).map((submission) => ({
      key: choiceKey({ workOrderId: record.order.id, number: submission.number }),
      label: `${record.order.id} submission ${submission.number}, ${summaryTail(submission)}`,
      submission,
      record,
    })));
}

/** The default choice: the newest order's shown submission. */
export function latestChoice<S>(view: OrderView<S>): SubmissionChoice {
  return { workOrderId: view.order.id, number: view.shown };
}

export type DiffRow =
  | { change: "added" | "removed" | "changed"; mark: string; step: string; text: string }
  | { change: "unchanged"; mark: string };

function stepText(step: ProcedureStep | RunStep): string {
  return "text" in step ? step.text : step.command;
}

function rowFor(change: StepChange, before: (ProcedureStep | RunStep)[], after: (ProcedureStep | RunStep)[]): DiffRow | null {
  switch (change.change) {
    case "same":
      return null;
    case "added":
      return { change: "added", mark: "Added", step: `Step ${change.after! + 1}`, text: stepText(after[change.after!]) };
    case "removed":
      return { change: "removed", mark: "Removed", step: `Step ${change.before! + 1}`, text: stepText(before[change.before!]) };
    case "changed": {
      const was = change.before! === change.after! ? "" : `, was step ${change.before! + 1}`;
      return {
        change: "changed", mark: `Changed: ${(change.fields ?? []).join(", ")}`,
        step: `Step ${change.after! + 1}${was}`, text: stepText(after[change.after!]),
      };
    }
  }
}

export function unchangedLabel(count: number): string {
  return count === 1 ? "1 unchanged step" : `${count} unchanged steps`;
}

/** A submission whose artifact couldn't be read as steps. */
export type UnreadableSide = { workOrderId: string; number: number };
export type DiffResult = { readable: true; rows: DiffRow[] } | { readable: false; unreadable: UnreadableSide[] };

/** `WO-1 submission 1's steps couldn't be read, so they can't be compared.` */
export function unreadableLine(side: UnreadableSide): string {
  return `${side.workOrderId} submission ${side.number}'s steps couldn't be read, so they can't be compared.`;
}

/**
 * The comparison of two submissions' artifact steps, `after` being the shown one. Each added,
 * removed or changed step is a row in step order; the unchanged steps are counted in one closing row.
 * When either artifact is malformed there is no comparison, only the sides that couldn't be read
 * (`before` first), so a broken artifact never reads as every step added or removed.
 */
export function diffRows(kind: "procedure" | "run_plan", before: Submission, after: Submission): DiffResult {
  const a = artifactSteps(kind, before.artifact);
  const b = artifactSteps(kind, after.artifact);
  if (a === null || b === null) {
    const unreadable = [[a, before] as const, [b, after] as const]
      .filter(([steps]) => steps === null)
      .map(([, s]) => ({ workOrderId: s.work_order_id, number: s.number }));
    return { readable: false, unreadable };
  }
  const changes = diffSteps(a, b);
  const rows = changes.map((c) => rowFor(c, a, b)).filter((r): r is DiffRow => r !== null);
  const same = changes.filter((c) => c.change === "same").length;
  if (same > 0) rows.push({ change: "unchanged", mark: unchangedLabel(same) });
  return { readable: true, rows };
}

// ---------------------------------------------------------------- built from

/** The first 12 characters of a digest, as "Built from" shows it. */
export function shortDigest(digest: string): string {
  return digest.slice(0, 12);
}

const PIN_LABELS: Record<Exclude<Pin["kind"], "skill">, string> = { lab: "Lab", project: "Project", experiment: "Experiment" };

/**
 * `Lab revision 1`, `Experiment revision 2`, `Skill How we write procedures revision 1`. Until the
 * skill titles are known (`null`) a skill reads `Skill revision 1`; a skill missing from them reads by its id.
 */
export function pinLabel(pin: Pin, skillTitles: ReadonlyMap<string, string> | null): string {
  if (pin.kind === "skill" && skillTitles === null) return `Skill revision ${pin.revision}`;
  const name = pin.kind === "skill" ? `Skill ${skillTitles?.get(pin.id) ?? pin.id}` : PIN_LABELS[pin.kind];
  return `${name} revision ${pin.revision}`;
}

/** The documents the steps cite, once each, in the order they first appear. */
export function citedSources(steps: { sources?: { id: string; title: string }[] }[]): { id: string; title: string }[] {
  const seen = new Map<string, { id: string; title: string }>();
  for (const step of steps) for (const source of step.sources ?? []) if (!seen.has(source.id)) seen.set(source.id, source);
  return [...seen.values()];
}

/**
 * `Approved by {name}, submission {n}, digest {12-char}, {date}` when the order is released and this is the
 * released submission, from the latest `approved` event; otherwise null.
 */
export function approvalLine(order: WorkOrder, submission: Submission, history: HistoryEvent[]): string | null {
  if (order.status !== "released" || order.released_submission !== submission.number) return null;
  const approved = [...history].reverse().find((h) => h.event === "approved");
  if (!approved) return null;
  return `Approved by ${approved.actor}, submission ${submission.number}, digest ${shortDigest(submission.artifact_digest)}, ${formatDate(approved.at)}`;
}
