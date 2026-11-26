"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import type { OutputKind, Workspace } from "../lib/types.ts";
import { AnalysisAppTab } from "./tabs/AnalysisAppTab.tsx";
import { ProcedureTab } from "./tabs/ProcedureTab.tsx";
import { ResultsTab } from "./tabs/ResultsTab.tsx";
import { RunPlanTab } from "./tabs/RunPlanTab.tsx";
import { SimulationTab } from "./tabs/SimulationTab.tsx";

export type PanelTab = "procedure" | "run_plan" | "analysis_app" | "results" | "simulation";

/** How each kind of output is named in the interface. */
export const OUTPUT_LABEL: Record<OutputKind, string> = {
  procedure: "Procedure",
  run_plan: "Run plan",
  analysis_app: "Analysis app",
  simulation: "Simulation",
};

export const TAB_LABEL: Record<PanelTab, string> = { ...OUTPUT_LABEL, results: "Results" };

/** The tabs a workspace has: only the outputs present, in a fixed order. Results comes with an analysis app. */
export function availableTabs(workspace: Workspace): PanelTab[] {
  const tabs: PanelTab[] = [];
  if (workspace.procedure) tabs.push("procedure");
  if (workspace.run_plan) tabs.push("run_plan");
  if (workspace.analysis_app) tabs.push("analysis_app", "results");
  if (workspace.simulation) tabs.push("simulation");
  return tabs;
}

/** Each tab's body lives in its own file under tabs/, so later tasks change only that file. */
function TabBody({ tab, workspace }: { tab: PanelTab; workspace: Workspace }): ReactNode {
  switch (tab) {
    case "procedure": return <ProcedureTab workspace={workspace} />;
    case "run_plan": return <RunPlanTab workspace={workspace} />;
    case "analysis_app": return <AnalysisAppTab workspace={workspace} />;
    case "results": return <ResultsTab workspace={workspace} />;
    case "simulation": return <SimulationTab workspace={workspace} />;
  }
}

export type OutputPanelProps = {
  workspace: Workspace;
  /** The selected tab. It must be one of availableTabs(workspace). */
  tab: PanelTab;
  onTab: (tab: PanelTab) => void;
  onClose: () => void;
};

/**
 * The built outputs, one tab each. A tab's body mounts the first time it is chosen and then stays
 * mounted (hidden while another tab is shown), so work done in it, such as a run, survives a
 * tab switch.
 */
export function OutputPanel({ workspace, tab, onTab, onClose }: OutputPanelProps) {
  const tabs = availableTabs(workspace);
  const [visited, setVisited] = useState<PanelTab[]>([tab]);
  if (!visited.includes(tab)) setVisited([...visited, tab]);
  const buttons = useRef(new Map<PanelTab, HTMLButtonElement>());

  // The selected tab stays in view, however the tab list lays out.
  useEffect(() => {
    buttons.current.get(tab)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [tab]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.indexOf(tab);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    onTab(tabs[next]);
    buttons.current.get(tabs[next])?.focus();
  }

  return (
    <section className="panel" aria-label="Outputs">
      <div className="panel-bar">
        <div className="panel-tabs" role="tablist" aria-label="Output tabs" onKeyDown={onKeyDown}>
          {tabs.map((t) => (
            <button
              key={t}
              ref={(el) => { if (el) buttons.current.set(t, el); else buttons.current.delete(t); }}
              type="button"
              role="tab"
              id={`panel-tab-${t}`}
              aria-selected={t === tab}
              aria-controls={visited.includes(t) ? `panel-body-${t}` : undefined}
              tabIndex={t === tab ? 0 : -1}
              className="panel-tab"
              onClick={() => onTab(t)}
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>
        <button type="button" className="panel-close" aria-label="Close panel" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </button>
      </div>
      {tabs.filter((t) => visited.includes(t)).map((t) => (
        <div
          key={t}
          role="tabpanel"
          id={`panel-body-${t}`}
          aria-labelledby={`panel-tab-${t}`}
          className="panel-body"
          hidden={t !== tab}
          tabIndex={0}
        >
          <TabBody tab={t} workspace={workspace} />
        </div>
      ))}
    </section>
  );
}
