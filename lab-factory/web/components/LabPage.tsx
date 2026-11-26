"use client";

import "./pages.css";

import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { Command, Lab } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";
import { errorText, kindLabel, sentenceCase } from "./pages-status.ts";
import { RangeStrip } from "./RangeStrip.tsx";
import { RevisionList } from "./RevisionList.tsx";

function plainWords(name: string): string {
  return name.replace(/_/g, " ");
}

function commandNeeds(c: Command): string {
  const needs = c.required.length > 0 ? `Needs ${c.required.map(plainWords).join(", ")}.` : "Needs nothing more.";
  return c.optional.length > 0 ? `${needs} Optional: ${c.optional.map(plainWords).join(", ")}.` : needs;
}

export function LabPage() {
  const { client, labId, version } = useClient();
  const [route] = useRoute();
  const [lab, setLab] = useState<Lab | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    client.getLab(labId).then(
      (l) => { if (live) { setLab(l); setError(null); } },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, version]);

  if (error) return <div className="page"><p role="alert" className="pg-error">{error}</p></div>;
  if (!lab) return <div className="page"><p className="pg-note">Loading</p></div>;

  return (
    <div className="page pg-page">
      <h1>Lab instruments and documents</h1>

      <section className="pg-section" aria-labelledby="pg-instruments">
        <h2 id="pg-instruments">Instruments</h2>
        {lab.instruments.map((i) => (
          <article key={i.id} className="pg-instrument" aria-labelledby={`pg-i-${i.id}`}>
            <h3 id={`pg-i-${i.id}`}>{i.name}</h3>
            <p className="pg-note">{i.model}, firmware {i.firmware}</p>
            {i.notes && <p>{i.notes}</p>}

            <h4>Commands</h4>
            <ul className="pg-list">
              {i.commands.map((c) => (
                <li key={c.name} className="pg-command">
                  <code>{c.name}</code>
                  <span className="pg-note">{commandNeeds(c)}</span>
                </li>
              ))}
            </ul>

            <h4>Allowed settings</h4>
            <div className="pg-strips">
              {i.parameters.map((p) => (
                <RangeStrip
                  key={p.name}
                  parameter={p.name}
                  label={sentenceCase(p.name)}
                  display={`${p.minimum}–${p.maximum} ${p.unit}`}
                  canonical={p}
                />
              ))}
            </div>
          </article>
        ))}
      </section>

      <section className="pg-section" aria-labelledby="pg-lab-docs">
        <h2 id="pg-lab-docs">Lab documents</h2>
        {lab.documents.length === 0 && <p className="pg-note">No documents yet.</p>}
        <ul className="pg-list">
          {lab.documents.map((d) => (
            <li key={d.id}>
              <a className="pg-row" href={routeHref({ ...route, doc: d.id })}>
                <span className="pg-row-title">{d.title}</span>
                <span className="pg-note">{kindLabel(d.kind)}</span>
              </a>
            </li>
          ))}
        </ul>
        <RevisionList kind="lab" id={labId} />
      </section>
    </div>
  );
}
