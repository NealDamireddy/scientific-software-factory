// How submissions and work orders read in the interface. Pure, so it runs under node --test.
// These only put the factory's results into words; they never decide pass or fail.
import type { AttentionItem, CheckResult, HistoryEvent, OutputKind, Submission, WorkOrder, WorkOrderStatus } from "./types.ts";

const OUTPUT_LABELS: Record<OutputKind, string> = {
  procedure: "Procedure",
  run_plan: "Run plan",
  analysis_app: "Analysis app",
  simulation: "Simulation",
};

export function outputLabel(kind: OutputKind): string {
  return OUTPUT_LABELS[kind];
}

/** `Submission 1, all checks passed`, `Submission 1, 1 check failed` or `Submission 1, 3 checks failed`. */
export function submissionSummary(s: Submission): string {
  const failed = s.results.filter((r) => !r.passed).length;
  if (failed === 1) return `Submission ${s.number}, 1 check failed`;
  if (failed > 1) return `Submission ${s.number}, ${failed} checks failed`;
  // A submission the factory did not pass never reads as passed, even without a failing result to count.
  if (!s.passed) return `Submission ${s.number}, checks did not pass`;
  return `Submission ${s.number}, all checks passed`;
}

/** A work order's status in one or two words, as the sidebar and status lines say it. */
const STATUS_WORDS: Record<WorkOrderStatus, string> = {
  released: "Signed off",
  in_review: "Waiting for sign-off",
  in_progress: "Being revised",
  open: "Not started",
};

/** What an experiment with no procedure order says instead of a status. */
export const NO_PROCEDURE = "No procedure yet";

/** The status word for an experiment's newest procedure order, or NO_PROCEDURE when it has none. */
export function statusWord(status: WorkOrderStatus | null): string {
  return status === null ? NO_PROCEDURE : STATUS_WORDS[status];
}

const ATTENTION_TEXT: Record<AttentionItem["kind"], string> = {
  sign_off: STATUS_WORDS.in_review,
  signed_off: STATUS_WORDS.released,
  rejected: "Rejected",
};

/** What a `Needs your attention` row says about its order. */
export function attentionText(kind: AttentionItem["kind"]): string {
  return ATTENTION_TEXT[kind];
}

/** Whether a submission's summary reads as a failure. */
export function submissionFailed(s: Submission): boolean {
  return !s.passed || s.results.some((r) => !r.passed);
}

/**
 * The shown submission's failing results that no step carries, matched by name and detail. The header
 * counts every failure, so these are listed on their own rather than dropped.
 */
export function unplacedFailures(results: CheckResult[], steps: { failures: CheckResult[] }[]): CheckResult[] {
  const placed = new Set(steps.flatMap((step) => step.failures.map((f) => JSON.stringify([f.name, f.detail]))));
  return results.filter((r) => !r.passed && !placed.has(JSON.stringify([r.name, r.detail])));
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** The work order's status as people read it, with names, dates and reasons from its history. */
export function statusLine(order: WorkOrder, history: HistoryEvent[]): string {
  switch (order.status) {
    case "in_progress":
    case "in_review":
      return STATUS_WORDS[order.status];
    case "released": {
      const approved = [...history].reverse().find((h) => h.event === "approved");
      return approved ? `Signed off by ${approved.actor} on ${formatDate(approved.at)}` : STATUS_WORDS.released;
    }
    case "open": {
      const last = history[history.length - 1];
      if (last && last.event === "rejected") return `Rejected by ${last.actor}: ${last.note}`;
      return STATUS_WORDS.open;
    }
  }
}

/** An error's message as the interface shows it. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
