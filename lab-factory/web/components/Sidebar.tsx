"use client";

import { ChevronDown, ChevronRight, FolderPlus, Plus, Search } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { MouseEvent } from "react";

import { routeHref } from "../lib/route.ts";
import { errorText, statusWord } from "../lib/status.ts";
import type { Route } from "../lib/route.ts";
import type { Experiment, Project, WorkOrderStatus } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { requestFocus } from "./focus-request.ts";
import type { FocusTarget } from "./focus-request.ts";
import { LabMenu } from "./LabMenu.tsx";
import { SampleIndicator } from "./SampleIndicator.tsx";

type ProjectRow = Project & { experiments: Pick<Experiment, "id" | "title">[] };
/** The newest procedure order's status per experiment id; null when it has no procedure. */
type Statuses = Record<string, WorkOrderStatus | null>;

function dotClass(status: WorkOrderStatus | null | undefined): string {
  if (status === "released") return "status-dot status-dot-released";
  if (status === "in_review") return "status-dot status-dot-review";
  return "status-dot";
}

/** A plain click on a `New` link focuses its form's field; a click that opens a new tab doesn't. */
function focusAfter(event: MouseEvent<HTMLAnchorElement>, target: FocusTarget): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  requestFocus(target);
}

function projectIdOf(route: Route): string | null {
  return route.view === "project" || route.view === "experiment" ? route.projectId : null;
}

const noSubscription = () => () => {};

/** Apple keyboards say ⌘K. Decided on the client; the prerendered page says `Ctrl K`. */
function onApple(): boolean {
  const data = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData;
  return [data?.platform, navigator.platform].some((p) => typeof p === "string" && /mac|iphone|ipad|ipod/i.test(p));
}

export function Sidebar({ onSearch, inert }: { onSearch: () => void; inert?: boolean }) {
  const shortcut = useSyncExternalStore(noSubscription, () => (onApple() ? "⌘K" : "Ctrl K"), () => "Ctrl K");
  const { client, labId, version } = useClient();
  const [route] = useRoute();
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [statuses, setStatuses] = useState<Statuses>({});
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let live = true;
    client.listProjects(labId).then(
      (rows) => {
        if (!live) return;
        setProjects(rows);
        setError(null);
        const ids = rows.flatMap((p) => p.experiments.map((e) => e.id));
        Promise.all(ids.map((id) => client.getWorkspace(id).then(
          (w) => [id, w.procedure?.order.status ?? null] as const,
          () => [id, null] as const,
        ))).then((pairs) => { if (live) setStatuses(Object.fromEntries(pairs)); });
      },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  // The project in the route is shown open. When the route moves to a project or one of its
  // experiments, a manual collapse of that project is forgotten, so the current link is never hidden.
  const currentProject = projectIdOf(route);
  const currentExperiment = route.view === "experiment" ? route.experimentId : null;
  const routeKey = `${currentProject ?? ""}\n${currentExperiment ?? ""}`;
  const [seenRouteKey, setSeenRouteKey] = useState(routeKey);
  if (seenRouteKey !== routeKey) {
    setSeenRouteKey(routeKey);
    if (currentProject !== null && expanded[currentProject] === false) {
      const { [currentProject]: _collapsed, ...rest } = expanded;
      setExpanded(rest);
    }
  }
  const isOpen = (id: string) => expanded[id] ?? id === currentProject;
  const newExperimentHref = routeHref(currentProject ? { view: "project", projectId: currentProject } : { view: "home" });
  const bottomLinks: [string, Route][] = [
    ["Lab instruments and documents", { view: "lab" }],
    ["Skills", { view: "skills" }],
    ["Connectors", { view: "connectors" }],
    ["Connect your agent", { view: "agents" }],
    ["Lab settings", { view: "settings" }],
  ];

  return (
    <nav className="sidebar" aria-label="Lab" inert={inert}>
      <LabMenu />
      <div className="sidebar-actions">
        <button
          type="button"
          className="sidebar-item"
          data-palette-trigger=""
          aria-haspopup="dialog"
          aria-keyshortcuts="Control+K Meta+K"
          onClick={onSearch}
        >
          <Search size={16} aria-hidden="true" />
          <span className="sidebar-item-label">Search</span>
          <kbd className="shortcut" aria-hidden="true">{shortcut}</kbd>
        </button>
        <a className="sidebar-item" href={newExperimentHref} onClick={(e) => focusAfter(e, "experiment-description")}>
          <Plus size={16} aria-hidden="true" />
          <span className="sidebar-item-label">New experiment</span>
        </a>
      </div>

      <section className="sidebar-projects" aria-labelledby="sidebar-projects-heading">
        <h2 id="sidebar-projects-heading" className="sidebar-heading">Projects</h2>
        {error && <p className="sidebar-note" role="alert">Couldn&apos;t load projects: {error}</p>}
        {!projects && !error && <p className="sidebar-note">Loading projects</p>}
        {projects && (
          <ul className="project-list">
            {projects.map((p) => {
              const open = isOpen(p.id);
              const listId = `sidebar-project-${p.id}`;
              const Chevron = open ? ChevronDown : ChevronRight;
              return (
                <li key={p.id}>
                  <div className="project-row">
                    <button
                      type="button"
                      className="project-toggle"
                      aria-expanded={open}
                      aria-controls={listId}
                      aria-label={p.title}
                      onClick={() => setExpanded((x) => ({ ...x, [p.id]: !open }))}
                    >
                      <Chevron size={16} aria-hidden="true" />
                    </button>
                    <a
                      className="sidebar-item project-link"
                      href={routeHref({ view: "project", projectId: p.id })}
                      aria-current={route.view === "project" && route.projectId === p.id ? "page" : undefined}
                    >
                      <span className="sidebar-item-label">{p.title}</span>
                    </a>
                  </div>
                  <ul id={listId} className="experiment-list" hidden={!open}>
                    {p.experiments.map((e) => {
                      const status = statuses[e.id];
                      return (
                        <li key={e.id}>
                          <a
                            className="sidebar-item experiment-link"
                            href={routeHref({ view: "experiment", projectId: p.id, experimentId: e.id })}
                            aria-current={currentExperiment === e.id && currentProject === p.id ? "page" : undefined}
                          >
                            <span className={dotClass(status)} aria-hidden="true" />
                            <span className="sidebar-item-label">{e.title}</span>
                            {status !== undefined && (
                              <span className="visually-hidden">, {statusWord(status)}</span>
                            )}
                          </a>
                        </li>
                      );
                    })}
                    {p.experiments.length === 0 && <li className="sidebar-note">No experiments yet</li>}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
        <a className="sidebar-item" href={routeHref({ view: "home" })} onClick={(e) => focusAfter(e, "project-title")}>
          <FolderPlus size={16} aria-hidden="true" />
          <span className="sidebar-item-label">New project</span>
        </a>
      </section>

      <div className="sidebar-bottom">
        <ul className="sidebar-links">
          {bottomLinks.map(([label, target]) => (
            <li key={label}>
              <a
                className="sidebar-item"
                href={routeHref(target)}
                aria-current={route.view === target.view ? "page" : undefined}
              >
                <span className="sidebar-item-label">{label}</span>
              </a>
            </li>
          ))}
        </ul>
        <SampleIndicator />
      </div>
    </nav>
  );
}
