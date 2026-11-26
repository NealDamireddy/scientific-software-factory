"use client";

import type { Workspace } from "../../lib/types.ts";
import { ResultsView } from "../ResultsView.tsx";

/** The Results tab: readings in, the analysis app's answer and plot out. */
export function ResultsTab({ workspace }: { workspace: Workspace }) {
  const app = workspace.analysis_app;
  if (!app) return <h2 className="panel-heading">Results</h2>;
  return <ResultsView app={app} />;
}
