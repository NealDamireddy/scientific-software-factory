"use client";

import type { Workspace } from "../../lib/types.ts";
import { ProcedureView } from "../ProcedureView.tsx";
import { SubmissionPanel } from "../SubmissionPanel.tsx";
import type { ShowOrderRequest } from "../SubmissionPanel.tsx";

/** The Procedure tab: the shown submission's header with its history, its steps and what it was built from. */
export function ProcedureTab({ workspace, request = null }: { workspace: Workspace; request?: ShowOrderRequest | null }) {
  const view = workspace.procedure;
  if (!view) return <h2 className="panel-heading">Procedure</h2>;
  return (
    <SubmissionPanel
      kind="procedure"
      experimentId={workspace.experiment.id}
      view={view}
      request={request}
      renderSteps={(steps, unplaced) => <ProcedureView steps={steps} unplaced={unplaced} />}
    />
  );
}
