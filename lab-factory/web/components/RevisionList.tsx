"use client";

import "./pages.css";

import { useEffect, useState } from "react";

import type { Pin, Revision } from "../lib/types.ts";
import { useClient } from "./ClientContext.tsx";
import { errorText, formatDate } from "./pages-status.ts";

/** Collapsed by default; re-fetches whenever the client's version changes. */
export function RevisionList({ kind, id }: { kind: Pin["kind"]; id: string }) {
  const { client, version } = useClient();
  const [revisions, setRevisions] = useState<Revision[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    client.listRevisions(kind, id).then(
      (rows) => { if (live) { setRevisions(rows); setError(null); } },
      (e: unknown) => { if (live) setError(errorText(e)); },
    );
    return () => { live = false; };
  }, [client, kind, id, version]);

  return (
    <details className="pg-revisions">
      <summary>Revision history</summary>
      {error && <p role="alert" className="pg-error">{error}</p>}
      {!revisions && !error && <p className="pg-note">Loading</p>}
      {revisions && (
        <ol className="pg-revision-list" aria-label="Revisions">
          {[...revisions].reverse().map((r) => (
            <li key={r.number}>
              <span className="pg-revision-head">
                <strong>Revision {r.number}</strong>
                <span className="pg-note">{formatDate(r.at)}</span>
                <code className="pg-digest">{r.digest.slice(0, 12)}</code>
              </span>
              {r.note && <span className="pg-note">{r.note}</span>}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
