"use client";

import type { Workspace } from "../../lib/types.ts";

/** The Run plan tab's body. Task 12 fills it with the run plan view and its submission header. */
export function RunPlanTab(_props: { workspace: Workspace }) {
  return <h2 className="panel-heading">Run plan</h2>;
}
