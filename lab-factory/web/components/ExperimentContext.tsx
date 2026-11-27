"use client";

import "./pages.css";

import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { Experiment, Instrument } from "../lib/types.ts";
import { AddDocument } from "./AddDocument.tsx";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText, kindLabel } from "./pages-status.ts";
import { RevisionList } from "./RevisionList.tsx";

/** The quiet header control that shows or hides the experiment's context. */
export function ExperimentContextToggle({ open, controls, onToggle }: { open: boolean; controls: string; onToggle: () => void }) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      className="ws-context-toggle"
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      title="Experiment context"
      onClick={onToggle}
    >
      <Chevron className="ws-context-chevron" size={16} aria-hidden="true" />
      <Info className="ws-context-info" size={18} aria-hidden="true" />
      {/* Where the conversation is narrow the words are kept for screen readers only. */}
      <span className="ws-context-toggle-label">Experiment context</span>
    </button>
  );
}

/**
 * What the factory reads for this experiment beyond the project and the lab: its goal, its
 * instruments and its documents, with a way to add a document and the revision history.
 */
export function ExperimentContext({ id, experiment }: { id: string; experiment: Experiment }) {
  const { client, labId, version } = useClient();
  const [route] = useRoute();
  const [instruments, setInstruments] = useState<Instrument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    client.getLab(labId).then(
      (lab) => { if (live) { setInstruments(lab.instruments); setError(null); } },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  const names = experiment.instrument_ids.map((i) => instruments?.find((x) => x.id === i)?.name ?? i);

  return (
    <section id={id} className="ws-context" aria-label="Experiment context">
      <div className="ws-context-grid">
        <div className="ws-context-part">
          <h2>Goal</h2>
          <p className="ws-context-goal">{experiment.goal.trim() || "No goal yet."}</p>
          <h2>Instruments</h2>
          {error && <p role="alert" className="pg-error">{error}</p>}
          {experiment.instrument_ids.length === 0 ? (
            <p className="pg-note">No instruments yet.</p>
          ) : instruments === null && !error ? (
            <p className="pg-note">Loading</p>
          ) : (
            <ul className="ws-context-names">{names.map((n, i) => <li key={`${n}-${i}`}>{n}</li>)}</ul>
          )}
        </div>
        <div className="ws-context-part">
          <h2>Documents</h2>
          {experiment.documents.length === 0 && <p className="pg-note">No documents yet.</p>}
          {experiment.documents.length > 0 && (
            <ul className="pg-list" aria-label="Experiment documents">
              {experiment.documents.map((d) => (
                <li key={d.id}>
                  <a className="pg-row" href={routeHref({ ...route, doc: d.id })}>
                    <span className="pg-row-title">{d.title}</span>
                    <span className="pg-note">{kindLabel(d.kind)}</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
          <details className="pg-revisions ws-context-add">
            <summary>Add a document</summary>
            <AddDocument target={{ kind: "experiment", id: experiment.id }} />
          </details>
          <RevisionList kind="experiment" id={experiment.id} />
        </div>
      </div>
    </section>
  );
}
