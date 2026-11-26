"use client";

import { shownSubmission } from "../../lib/status.ts";
import type { Workspace } from "../../lib/types.ts";
import { RunPlanView } from "../RunPlanView.tsx";
import { SubmissionHeader } from "../SubmissionHeader.tsx";

/** The Run plan tab: the shown submission's header and its command lines. */
export function RunPlanTab({ workspace }: { workspace: Workspace }) {
  const view = workspace.run_plan;
  if (!view) return <h2 className="panel-heading">Run plan</h2>;
  const submission = shownSubmission(view);
  return (
    <>
      <SubmissionHeader order={view.order} submission={submission} history={view.history} />
      {submission && <RunPlanView steps={view.steps} />}
    </>
  );
}
