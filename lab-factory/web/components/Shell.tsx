"use client";

import { useCallback, useEffect, useState } from "react";
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
function KnownIds({ projectId, experimentId, children }: { projectId: string; experimentId?: string; children: ReactNode }) {
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
        setCheck({ key, result: missing ? "missing" : { error: e instanceof Error ? e.message : String(e) } });
      },
    );
    return () => { live = false; };
  }, [client, projectId, experimentId, key, version]);

  // A result for other ids (the route just changed) counts as still checking. After the first
  // check, re-checks on refresh keep showing the view.
  const result = check.key === key ? check.result : "checking";
  if (result === "checking") return null;
  if (result === "missing") return <NotFound />;
  if (result !== "found") {
    return <div className="page"><p role="alert">Couldn&apos;t open this page: {result.error}</p></div>;
  }
  return <>{children}</>;
}

export function Shell() {
  const { mode } = useClient();
  const [route] = useRoute();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const closePalette = useCallback(() => setPaletteOpen(false), []);

  let view = <View route={route} />;
  if (route.view === "project") view = <KnownIds projectId={route.projectId}>{view}</KnownIds>;
  if (route.view === "experiment") {
    view = <KnownIds projectId={route.projectId} experimentId={route.experimentId}>{view}</KnownIds>;
  }

  return (
    <div className={mode === "sample" ? "shell shell-sample" : "shell"}>
      {/* While the palette is open, everything behind it is inert. */}
      <Sidebar onSearch={openPalette} inert={paletteOpen} />
      <main className="content" inert={paletteOpen}>{view}</main>

      <DocumentDrawer />

      <CommandPalette open={paletteOpen} onOpen={openPalette} onClose={closePalette} />
    </div>
  );
}
