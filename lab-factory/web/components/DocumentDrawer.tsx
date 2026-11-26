"use client";

import "./pages.css";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Document } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText, kindLabel } from "./pages-status.ts";

type Found = { document: Document; belongs: string };
type Result = { key: string; found: Found | null; error?: string };

/** A non-modal side panel for the document named by the route's `doc`. */
export function DocumentDrawer() {
  const { client, labId, version } = useClient();
  const [route, navigate] = useRoute();
  const doc = route.doc;
  const projectId = route.view === "project" || route.view === "experiment" ? route.projectId : undefined;
  const experimentId = route.view === "experiment" ? route.experimentId : undefined;
  const key = `${doc ?? ""}\n${projectId ?? ""}\n${experimentId ?? ""}`;
  const [result, setResult] = useState<Result | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!doc) return;
    let live = true;
    (async () => {
      const lab = await client.getLab(labId);
      let found: Found | null = null;
      const inLab = lab.documents.find((d) => d.id === doc);
      if (inLab) found = { document: inLab, belongs: "Lab" };
      if (!found && projectId) {
        const project = await client.getProject(projectId).catch(() => null);
        const inProject = project?.documents.find((d) => d.id === doc);
        if (project && inProject) found = { document: inProject, belongs: `Project ${project.title}` };
        if (!found && project && experimentId) {
          const experiment = project.experiments.find((x) => x.id === experimentId);
          const inExperiment = experiment?.documents.find((d) => d.id === doc);
          if (experiment && inExperiment) found = { document: inExperiment, belongs: `Experiment ${experiment.title}` };
        }
      }
      if (live) setResult({ key, found });
    })().catch((e: unknown) => { if (live) setResult({ key, found: null, error: errorText(e) }); });
    return () => { live = false; };
  }, [client, labId, doc, projectId, experimentId, key, version]);

  // Remember what had focus when the drawer opened, and give it back when the drawer closes.
  const open = doc !== undefined;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    opener.current = previous && previous !== document.body ? previous : null;
    return () => {
      const target = opener.current;
      opener.current = null;
      if (target && target.isConnected) target.focus();
    };
  }, [open]);

  const shown = open && result?.key === key ? result : null;
  const ready = shown !== null;
  // Focus moves to the heading once per opened document.
  useEffect(() => {
    if (ready) heading.current?.focus();
  }, [ready, doc]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (document.querySelector('[role="dialog"]')) return;
      const target = e.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select")) return;
      const { doc: _doc, ...rest } = route;
      navigate(rest);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, route, navigate]);

  if (!open || !shown) return null;
  const close = () => { const { doc: _doc, ...rest } = route; navigate(rest); };

  return (
    <aside className="drawer" aria-label="Document">
      <div className="drawer-bar">
        <button type="button" className="pg-button pg-quiet" onClick={close}>
          <X size={16} aria-hidden="true" />
          Close
        </button>
      </div>
      {shown.error && <p role="alert" className="pg-error">{shown.error}</p>}
      {!shown.error && !shown.found && (
        <>
          <h2 ref={heading} tabIndex={-1} className="drawer-title">Document</h2>
          <p>That document isn&apos;t here.</p>
        </>
      )}
      {shown.found && (
        <>
          <h2 ref={heading} tabIndex={-1} className="drawer-title">{shown.found.document.title}</h2>
          <dl className="drawer-facts">
            <div><dt>Kind</dt><dd>{kindLabel(shown.found.document.kind)}</dd></div>
            <div><dt>Source</dt><dd>{shown.found.document.source}</dd></div>
            <div><dt>Belongs to</dt><dd>{shown.found.belongs}</dd></div>
          </dl>
          <pre className="drawer-text">{shown.found.document.text}</pre>
        </>
      )}
    </aside>
  );
}
