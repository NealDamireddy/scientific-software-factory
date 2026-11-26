"use client";

import { CircleCheck, CircleX } from "lucide-react";
import type { ReactNode } from "react";

import { statusLine, submissionFailed, submissionSummary } from "../lib/status.ts";
import type { HistoryEvent, Submission, WorkOrder } from "../lib/types.ts";

export type SubmissionHeaderProps = {
  order: WorkOrder;
  /** The submission on show; undefined when nothing has been submitted yet. */
  submission: Submission | undefined;
  history: HistoryEvent[];
  /** Actions for the shown submission: the submission picker and compare (Task 13), sign-off (Task 15). */
  children?: ReactNode;
};

/**
 * The tab's heading: the shown submission's check summary, then the order's status as people read it.
 * A failing summary is styled as a failure, but its words carry it on their own.
 */
export function SubmissionHeader({ order, submission, history, children }: SubmissionHeaderProps) {
  const failed = submission ? submissionFailed(submission) : false;
  return (
    <header className="sub-header">
      {submission ? (
        <h2 className="sub-summary" data-failed={failed ? "true" : "false"}>
          {failed
            ? <CircleX className="sub-icon" size={18} aria-hidden="true" />
            : <CircleCheck className="sub-icon" size={18} aria-hidden="true" />}
          <span>{submissionSummary(submission)}</span>
        </h2>
      ) : (
        <h2 className="sub-summary">No submissions yet</h2>
      )}
      <p className="sub-status">{statusLine(order, history)}</p>
      {children !== undefined && children !== null && children !== false && <div className="sub-actions">{children}</div>}
    </header>
  );
}
