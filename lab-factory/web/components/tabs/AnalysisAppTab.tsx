"use client";

import type { Workspace } from "../../lib/types.ts";
import { AnalysisAppView } from "../AnalysisAppView.tsx";

/** The Analysis app tab: the summary, the code and the reference cases, run in the browser. */
export function AnalysisAppTab({ workspace }: { workspace: Workspace }) {
  const app = workspace.analysis_app;
  if (!app) return <h2 className="panel-heading">Analysis app</h2>;
  // Keyed by the app, so another app's cases never show this one's answers.
  return <AnalysisAppView key={JSON.stringify([app.entry, app.code, app.reference_cases])} app={app} />;
}
