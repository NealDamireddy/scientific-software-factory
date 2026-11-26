"use client";

import { shownSubmission } from "../../lib/status.ts";
import type { Workspace } from "../../lib/types.ts";
import { ProcedureView } from "../ProcedureView.tsx";
import { SubmissionHeader } from "../SubmissionHeader.tsx";

/** The Procedure tab: the shown submission's header and its steps. */
export function ProcedureTab({ workspace }: { workspace: Workspace }) {
  const view = workspace.procedure;
  if (!view) return <h2 className="panel-heading">Procedure</h2>;
  const submission = shownSubmission(view);
  return (
    <>
      <SubmissionHeader order={view.order} submission={submission} history={view.history} />
      {submission && <ProcedureView steps={view.steps} />}
    </>
  );
}
