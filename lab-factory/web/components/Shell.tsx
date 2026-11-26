"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import type { Route } from "../lib/route.ts";
import { ClientError } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { CommandPalette } from "./CommandPalette.tsx";
import { NotFound } from "./NotFound.tsx";
import { Sidebar } from "./Sidebar.tsx";
import { LabHome } from "./LabHome.tsx";
import { ProjectPage } from "./ProjectPage.tsx";
import { LabPage } from "./LabPage.tsx";
import { SettingsPage } from "./SettingsPage.tsx";
import { DocumentDrawer } from "./DocumentDrawer.tsx";
import { SkillsPage } from "./SkillsPage.tsx";
import { ConnectorsPage } from "./ConnectorsPage.tsx";
import { AgentsPage } from "./AgentsPage.tsx";
import { Workspace } from "./Workspace.tsx";
import { errorText } from "../lib/status.ts";

/** Each route maps to exactly one view. */
function View({ route }: { route: Route }) {
  switch (route.view) {
    case "home": return <LabHome />;
    case "lab": return <LabPage />;
    case "settings": return <SettingsPage />;
    case "skills": return <SkillsPage skill={route.skill} />;
    case "connectors": return <ConnectorsPage />;
    case "agents": return <AgentsPage />;
    case "project": return <ProjectPage projectId={route.projectId} />;
    case "experiment": return <Workspace projectId={route.projectId} experimentId={route.experimentId} />;
  }
}

type Check = "checking" | "found" | "missing" | { error: string };

/**
 * Project and experiment routes come from bookmarks and links, so their ids are checked with the
 * client before the view renders: an unknown project, or an experiment outside that project, is
 * not found.
 */
function KnownIds({ projectId, experimentId, onResolved, children }: {
  projectId: string; experimentId?: string; onResolved: () => void; children: ReactNode;
}) {
  const { client, version } = useClient();
  const [check, setCheck] = useState<{ key: string; result: Check }>({ key: "", result: "checking" });
  const key = `${projectId}\n${experimentId ?? ""}`;

  useEffect(() => {
    let live = true;
    client.getProject(projectId).then(
      (project) => {
        const found = experimentId === undefined || project.experiments.some((e) => e.id === experimentId);
        if (live) setCheck({ key, result: found ? "found" : "missing" });
      },
      (e: unknown) => {
        if (!live) return;
        const missing = e instanceof ClientError && e.code === "not_found";
        setCheck({ key, result: missing ? "missing" : { error: errorText(e) } });
      },
    );
    return () => { live = false; };
  }, [client, projectId, experimentId, key, version]);

  // A result for other ids (the route just changed) counts as still checking. After the first
  // check, re-checks on refresh keep showing the view.
  const result = check.key === key ? check.result : "checking";
  useEffect(() => {
    if (result !== "checking") onResolved();
  }, [result, onResolved]);
  if (result === "checking") return null;
  if (result === "missing") return <NotFound />;
  if (result !== "found") {
    return (
      <div className="page">
        <h1>Something went wrong</h1>
        <p role="alert">Couldn&apos;t open this page: {result.error}</p>
      </div>
    );
  }
  return <>{children}</>;
}

const noSubscription = () => () => {};

/** False in the prerendered page and while it hydrates, true once the app runs on the client. */
function useMounted(): boolean {
  return useSyncExternalStore(noSubscription, () => true, () => false);
}

export function Shell() {
  const { mode } = useClient();
  const [route] = useRoute();
  const mounted = useMounted();
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Whether the first route has resolved: at once for most views, after the id check for a
  // project or experiment.
  const [resolved, setResolved] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const closePalette = useCallback(() => setPaletteOpen(false), []);
  const markResolved = useCallback(() => setResolved(true), []);
  const checksIds = route.view === "project" || route.view === "experiment";

  useEffect(() => {
    if (mounted && !checksIds) setResolved(true);
  }, [mounted, checksIds]);

  let view = <View route={route} />;
  if (route.view === "project") view = <KnownIds projectId={route.projectId} onResolved={markResolved}>{view}</KnownIds>;
  if (route.view === "experiment") {
    view = (
      <KnownIds projectId={route.projectId} experimentId={route.experimentId} onResolved={markResolved}>{view}</KnownIds>
    );
  }

  // The static export prerenders without a route (the hash never reaches the server), so until the
  // app has mounted the main area stays empty: a deep link never flashes the lab home first.
  // The sidebar is drawn but inert until then, so nothing is clicked before it works.
  return (
    <div className={mode === "sample" ? "shell shell-sample" : "shell"} data-ready={mounted && resolved ? "true" : "false"}>
      {/* While the palette is open, everything behind it is inert. */}
      <Sidebar onSearch={openPalette} inert={paletteOpen || !mounted} />
      <main className="content" inert={paletteOpen}>
        <noscript><p className="noscript">Lab Factory needs JavaScript to run.</p></noscript>
        {mounted ? view : null}
      </main>

      <DocumentDrawer />

      <CommandPalette open={paletteOpen} onOpen={openPalette} onClose={closePalette} />
    </div>
  );
}
