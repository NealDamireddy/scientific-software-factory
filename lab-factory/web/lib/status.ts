// How submissions and work orders read in the interface. Pure, so it runs under node --test.
// These only put the factory's results into words; they never decide pass or fail.
import type { HistoryEvent, OrderView, OutputKind, Submission, WorkOrder } from "./types.ts";

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

/** The submission an order view shows, or undefined when nothing has been submitted yet. */
export function shownSubmission<S>(view: OrderView<S>): Submission | undefined {
  return view.submissions.find((s) => s.number === view.shown);
}

/** Whether a submission's summary reads as a failure. */
export function submissionFailed(s: Submission): boolean {
  return !s.passed || s.results.some((r) => !r.passed);
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
      return "Being revised";
    case "in_review":
      return "Waiting for sign-off";
    case "released": {
      const approved = [...history].reverse().find((h) => h.event === "approved");
      return approved ? `Signed off by ${approved.actor} on ${formatDate(approved.at)}` : "Signed off";
    }
    case "open": {
      const last = history[history.length - 1];
      if (last && last.event === "rejected") return `Rejected by ${last.actor}: ${last.note}`;
      return "Not started";
    }
  }
}
