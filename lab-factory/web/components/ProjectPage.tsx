"use client";

import "./pages.css";

import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { Experiment, Project } from "../lib/types.ts";
import { AddDocument } from "./AddDocument.tsx";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText, kindLabel, procedureStatusLine } from "./pages-status.ts";
import { RevisionList } from "./RevisionList.tsx";
import { StartExperiment } from "./StartExperiment.tsx";

type Loaded = Project & { experiments: Experiment[] };

export function ProjectPage({ projectId }: { projectId: string }) {
  const { client, version } = useClient();
  const [route] = useRoute();
  const [project, setProject] = useState<Loaded | null>(null);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    client.getProject(projectId).then(
      (p) => {
        if (!live) return;
        setProject(p);
        setError(null);
        Promise.all(p.experiments.map((e) => client.getWorkspace(e.id).then(
          (w) => [e.id, procedureStatusLine(w.procedure)] as const,
          () => [e.id, "No procedure yet"] as const,
        ))).then((pairs) => { if (live) setStatuses(Object.fromEntries(pairs)); });
      },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, projectId, version]);

  if (error) return <div className="page"><p role="alert" className="pg-error">{error}</p></div>;
  // A project that was loaded for another route stays hidden until its own data arrives.
  if (!project || project.id !== projectId) return <div className="page"><p className="pg-note">Loading</p></div>;

  return (
    <div className="page pg-page pg-wide">
      <div className="pg-project">
        <div className="pg-main">
          <h1>{project.title}</h1>
          <p className="pg-goals">{project.goals}</p>

          <section className="pg-section" aria-labelledby="pg-experiments">
            <h2 id="pg-experiments">Experiments</h2>
            {project.experiments.length === 0 && <p className="pg-note">No experiments yet.</p>}
            <ul className="pg-list">
              {project.experiments.map((e) => (
                <li key={e.id}>
                  <a className="pg-row" href={routeHref({ view: "experiment", projectId, experimentId: e.id })}>
                    <span className="pg-row-title">{e.title}</span>
                    <span className="pg-note">{statuses[e.id] ?? " "}</span>
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <section className="pg-section" aria-labelledby="pg-start">
            <h2 id="pg-start">New experiment</h2>
            <StartExperiment projectId={projectId} />
          </section>
        </div>

        <aside className="pg-aside" aria-labelledby="pg-shared">
          <h2 id="pg-shared">Shared with every experiment in this project</h2>
          {project.documents.length === 0 && <p className="pg-note">No documents yet.</p>}
          <ul className="pg-list">
            {project.documents.map((d) => (
              <li key={d.id}>
                <a className="pg-row" href={routeHref({ ...route, doc: d.id })}>
                  <span className="pg-row-title">{d.title}</span>
                  <span className="pg-note">{kindLabel(d.kind)}</span>
                </a>
              </li>
            ))}
          </ul>
          <h3>Add a document</h3>
          <AddDocument target={{ kind: "project", id: projectId }} />
          <RevisionList kind="project" id={projectId} />
        </aside>
      </div>
    </div>
  );
}
