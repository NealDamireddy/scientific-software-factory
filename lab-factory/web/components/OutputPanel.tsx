"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { outputLabel } from "../lib/status.ts";
import type { Workspace } from "../lib/types.ts";
import { AnalysisAppTab } from "./tabs/AnalysisAppTab.tsx";
import { ProcedureTab } from "./tabs/ProcedureTab.tsx";
import { ResultsTab } from "./tabs/ResultsTab.tsx";
import { RunPlanTab } from "./tabs/RunPlanTab.tsx";
import type { ShowOrderRequest } from "./SubmissionPanel.tsx";
import { SimulationTab } from "./tabs/SimulationTab.tsx";

export type PanelTab = "procedure" | "run_plan" | "analysis_app" | "results" | "simulation";

/** A tab is named after its output (lib/status.ts); Results comes with the analysis app. */
function tabLabel(tab: PanelTab): string {
  return tab === "results" ? "Results" : outputLabel(tab);
}

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
function TabBody({ tab, workspace, request }: { tab: PanelTab; workspace: Workspace; request: ShowOrderRequest | null }): ReactNode {
  switch (tab) {
    case "procedure": return <ProcedureTab workspace={workspace} request={request} />;
    case "run_plan": return <RunPlanTab workspace={workspace} request={request} />;
    case "analysis_app": return <AnalysisAppTab workspace={workspace} />;
    case "results": return <ResultsTab workspace={workspace} />;
    case "simulation": return <SimulationTab workspace={workspace} />;
  }
}

/** Scrolls the tab strip, and only the strip, so the button is fully inside it. */
function revealInStrip(strip: HTMLElement, button: HTMLElement): void {
  const s = strip.getBoundingClientRect();
  const b = button.getBoundingClientRect();
  if (b.left < s.left) strip.scrollLeft -= s.left - b.left;
  else if (b.right > s.right) strip.scrollLeft += b.right - s.right;
  if (b.top < s.top) strip.scrollTop -= s.top - b.top;
  else if (b.bottom > s.bottom) strip.scrollTop += b.bottom - s.bottom;
}

export type OutputPanelProps = {
  workspace: Workspace;
  /** The selected tab. It must be one of availableTabs(workspace). */
  tab: PanelTab;
  onTab: (tab: PanelTab) => void;
  onClose: () => void;
  /** An output card's request to show a work order's latest submission in its tab. */
  orderRequest?: ShowOrderRequest | null;
};

/**
 * The built outputs, one tab each. A tab's body mounts the first time it is chosen and then stays
 * mounted (hidden while another tab is shown), so work done in it, such as a run, survives a
 * tab switch.
 */
export function OutputPanel({ workspace, tab, onTab, onClose, orderRequest = null }: OutputPanelProps) {
  const tabs = availableTabs(workspace);
  const [visited, setVisited] = useState<PanelTab[]>([tab]);
  if (!visited.includes(tab)) setVisited([...visited, tab]);
  const buttons = useRef(new Map<PanelTab, HTMLButtonElement>());
  const strip = useRef<HTMLDivElement>(null);
  // Set when the person picks a tab; only then is the strip scrolled, and never the window.
  const chosen = useRef(false);

  useEffect(() => {
    if (!chosen.current) return;
    chosen.current = false;
    const button = buttons.current.get(tab);
    if (strip.current && button) revealInStrip(strip.current, button);
  }, [tab]);

  function choose(next: PanelTab) {
    chosen.current = true;
    onTab(next);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.indexOf(tab);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    choose(tabs[next]);
    buttons.current.get(tabs[next])?.focus();
  }

  return (
    <section className="panel" aria-label="Outputs">
      <div className="panel-bar">
        <div ref={strip} className="panel-tabs" role="tablist" aria-label="Output tabs" onKeyDown={onKeyDown}>
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
              onClick={() => choose(t)}
            >
              {tabLabel(t)}
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
          <TabBody tab={t} workspace={workspace} request={orderRequest} />
        </div>
      ))}
    </section>
  );
}
