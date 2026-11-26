"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { approvalLine, pinLabel, shortDigest } from "../lib/history.ts";
import { routeHref } from "../lib/route.ts";
import type { HistoryEvent, Submission, WorkOrder } from "../lib/types.ts";
import { useRoute } from "./ClientContext.tsx";

const COPIED_MS = 2000;

type LineProps = {
  label: string;
  digest: string;
  copyName: string;
  /** This line's copy failed: the full digest is offered to copy by hand. */
  failed: boolean;
  onCopied: () => void;
  onFailed: () => void;
};

/**
 * One pinned revision or the artifact: its label, the digest's first 12 characters and a copy button
 * for the full digest, with `Copied` announced beside it. When copying fails, the full digest shows
 * on the line in a selected, read-only field.
 */
function DigestLine({ label, digest, copyName, failed, onCopied, onFailed }: LineProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useLayoutEffect(() => {
    if (!failed) return;
    field.current?.focus();
    field.current?.select();
  }, [failed]);

  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(digest);
      setCopied(true);
      onCopied();
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      setCopied(false);
      onFailed();
    }
  }

  return (
    <li className="hist-built-line">
      <span className="hist-built-label">{label}</span>
      <code className="hist-digest">{shortDigest(digest)}</code>
      <span className="hist-copy">
        <span role="status" className="hist-copied">{copied ? "Copied" : ""}</span>
        <button type="button" className="ws-button hist-quiet" aria-label={copyName} onClick={copy}>Copy</button>
      </span>
      {failed && (
        <span className="hist-copy-fallback">
          <span role="alert" className="hist-copy-error">Couldn&apos;t copy. Copy the digest below.</span>
          <input
            ref={field}
            className="hist-copy-field"
            type="text"
            readOnly
            value={digest}
            aria-label={`${label} digest`}
            spellCheck={false}
            onFocus={(e) => e.currentTarget.select()}
          />
        </span>
      )}
    </li>
  );
}

export type BuiltFromProps = {
  /** The shown submission's order, whose pins it was built from. */
  order: WorkOrder;
  submission: Submission;
  history: HistoryEvent[];
  /** The documents the shown steps cite, once each (see `citedSources`); null while the steps load. */
  sources: { id: string; title: string }[] | null;
  /** The lab's skill titles by id; null until they arrive. */
  skillTitles: ReadonlyMap<string, string> | null;
  skillError?: string | null;
};

/**
 * Traceability for the shown submission: the pinned revisions, the artifact digest, the cited documents
 * and the approval. It stays mounted while the shown submission changes, so it keeps its open state.
 */
export function BuiltFrom({ order, submission, history, sources, skillTitles, skillError }: BuiltFromProps) {
  const [route] = useRoute();
  // Only one line offers its digest by hand at a time; it resets when another submission is shown.
  const [failed, setFailed] = useState<{ owner: string; line: string } | null>(null);
  const owner = `${order.id}#${submission.number}`;
  const failedLine = failed && failed.owner === owner ? failed.line : null;

  const approved = approvalLine(order, submission, history);
  const lines = [
    ...order.pins.map((pin) => {
      const label = pinLabel(pin, skillTitles);
      return { key: `${pin.kind}:${pin.id}`, label, digest: pin.digest, copyName: `Copy ${label} digest` };
    }),
    { key: "artifact", label: "Artifact", digest: submission.artifact_digest, copyName: "Copy artifact digest" },
  ];
  return (
    <details className="hist-built">
      <summary className="hist-built-summary">Built from</summary>
      <div className="hist-built-body">
        <ul className="hist-built-lines" role="list">
          {lines.map((line) => (
            <DigestLine
              key={line.key}
              label={line.label}
              digest={line.digest}
              copyName={line.copyName}
              failed={failedLine === line.key}
              onCopied={() => setFailed((f) => (f && f.owner === owner && f.line === line.key ? null : f))}
              onFailed={() => setFailed({ owner, line: line.key })}
            />
          ))}
        </ul>
        {skillError && <p role="alert" className="pg-error">{skillError}</p>}
        {sources !== null && (
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
        )}
        {approved && <p className="hist-built-approval">{approved}</p>}
      </div>
    </details>
  );
}
