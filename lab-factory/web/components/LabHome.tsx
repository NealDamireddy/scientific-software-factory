"use client";

import "./pages.css";

import { useEffect, useState } from "react";

import { routeHref } from "../lib/route.ts";
import type { AttentionItem } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { NewProject } from "./NewProject.tsx";
import { attentionText } from "../lib/status.ts";
import { errorText } from "./pages-status.ts";
import { StartExperiment } from "./StartExperiment.tsx";

export function LabHome() {
  const { client, labId, role, version } = useClient();
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    client.needsAttention(labId, role).then(
      (rows) => { if (live) { setItems(rows); setError(null); } },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, labId, role, version]);

  return (
    <div className="page pg-page">
      <h1>What are you working on?</h1>
      <StartExperiment />

      <section className="pg-section" aria-labelledby="pg-attention">
        <h2 id="pg-attention">Needs your attention</h2>
        {error && <p role="alert" className="pg-error">{error}</p>}
        {items && items.length === 0 && <p className="pg-note">Nothing needs you right now.</p>}
        {items && items.length > 0 && (
          <ul className="pg-list">
            {items.map((item) => (
              <li key={`${item.work_order_id}-${item.kind}`}>
                <a
                  className="pg-row"
                  href={routeHref({ view: "experiment", projectId: item.project_id, experimentId: item.experiment_id })}
                >
                  <span className="pg-row-title">{item.title}</span>{" "}
                  <span className="pg-note">{attentionText(item.kind)}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="pg-section" aria-labelledby="pg-new-project">
        <h2 id="pg-new-project">New project</h2>
        <NewProject />
      </section>
    </div>
  );
}
