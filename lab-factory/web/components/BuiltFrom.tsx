"use client";

import { useEffect, useRef, useState } from "react";

import { approvalLine, pinLabel, shortDigest } from "../lib/history.ts";
import { routeHref } from "../lib/route.ts";
import type { HistoryEvent, Submission, WorkOrder } from "../lib/types.ts";
import { ClientError } from "../lib/types.ts";
import { useClient, useRoute } from "./ClientContext.tsx";

const COPIED_MS = 2000;

/** A copy button for a full digest, with `Copied` announced beside it (the pattern CopyField uses). */
function DigestCopy({ name, digest }: { name: string; digest: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(digest);
      setFailed(false);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      setCopied(false);
      setFailed(true);
    }
  }

  return (
    <>
      <span className="hist-copy">
        <span role="status" className="hist-copied">{copied ? "Copied" : ""}</span>
        <button type="button" className="ws-button hist-quiet" aria-label={name} onClick={copy}>Copy</button>
      </span>
      {failed && <p role="alert" className="pg-error hist-copy-error">Couldn&apos;t copy. Select the digest and copy it yourself.</p>}
    </>
  );
}

function DigestLine({ label, digest, copyName }: { label: string; digest: string; copyName: string }) {
  return (
    <li className="hist-built-line">
      <span className="hist-built-label">{label}</span>
      <code className="hist-digest">{shortDigest(digest)}</code>
      <DigestCopy name={copyName} digest={digest} />
    </li>
  );
}

export type BuiltFromProps = {
  /** The shown submission's order, whose pins it was built from. */
  order: WorkOrder;
  submission: Submission;
  history: HistoryEvent[];
  /** The documents the shown steps cite, once each (see `citedSources`). */
  sources: { id: string; title: string }[];
};

/** Traceability for the shown submission: the pinned revisions, the artifact digest, the cited documents and the approval. */
export function BuiltFrom({ order, submission, history, sources }: BuiltFromProps) {
  const { client, labId, version } = useClient();
  const [route] = useRoute();
  const [titles, setTitles] = useState<ReadonlyMap<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const hasSkills = order.pins.some((p) => p.kind === "skill");

  useEffect(() => {
    if (!hasSkills) return;
    let live = true;
    client.listSkills(labId).then(
      (skills) => {
        if (!live) return;
        setTitles(new Map(skills.map((s) => [s.id, s.title])));
        setError(null);
      },
      (e: unknown) => {
        if (live) setError(e instanceof ClientError ? e.message : "Couldn't load the lab's skills.");
      },
    );
    return () => { live = false; };
  }, [client, labId, version, hasSkills]);

  const approved = approvalLine(order, submission, history);
  return (
    <details className="hist-built">
      <summary className="hist-built-summary">Built from</summary>
      <div className="hist-built-body">
        <ul className="hist-built-lines" role="list">
          {order.pins.map((pin) => {
            const label = pinLabel(pin, titles);
            return <DigestLine key={`${pin.kind}:${pin.id}`} label={label} digest={pin.digest} copyName={`Copy ${label} digest`} />;
          })}
          <DigestLine label="Artifact" digest={submission.artifact_digest} copyName="Copy artifact digest" />
        </ul>
        {error && <p role="alert" className="pg-error">{error}</p>}
        <div className="hist-built-docs">
          <p className="hist-built-head">Cited documents</p>
          {sources.length === 0 ? (
            <p className="hist-built-none">No documents cited.</p>
          ) : (
            <ul className="hist-built-doclist" role="list">
              {sources.map((s) => (
                <li key={s.id}><a className="proc-source hist-doc" href={routeHref({ ...route, doc: s.id })}>{s.title}</a></li>
              ))}
            </ul>
          )}
        </div>
        {approved && <p className="hist-built-approval">{approved}</p>}
      </div>
    </details>
  );
}
