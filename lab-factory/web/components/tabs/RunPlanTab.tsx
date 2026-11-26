"use client";

import type { Workspace } from "../../lib/types.ts";
import { RunPlanView } from "../RunPlanView.tsx";
import { SubmissionPanel } from "../SubmissionPanel.tsx";

/** The Run plan tab: the shown submission's header with its history, its command lines and what it was built from. */
export function RunPlanTab({ workspace }: { workspace: Workspace }) {
  const view = workspace.run_plan;
  if (!view) return <h2 className="panel-heading">Run plan</h2>;
  return (
    <SubmissionPanel
      kind="run_plan"
      experimentId={workspace.experiment.id}
      view={view}
      renderSteps={(steps, unplaced) => <RunPlanView steps={steps} unplaced={unplaced} />}
    />
  );
}
