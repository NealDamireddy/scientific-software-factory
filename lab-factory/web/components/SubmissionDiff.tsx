"use client";

import { useEffect, useId, useMemo, useState } from "react";

import { diffRows, unreadableLine } from "../lib/history.ts";
import type { SubmissionOption } from "../lib/history.ts";
import { useClient } from "./ClientContext.tsx";

export type SubmissionDiffProps = {
  /** The section's id, for the Compare button's `aria-controls`. */
  id: string;
  kind: "procedure" | "run_plan";
  /** The shown submission: the "after" side. */
  shown: SubmissionOption;
  /** Every submission, newest first; all but the shown one can be compared with it. */
  options: SubmissionOption[];
  /** Document titles by id, from the step views on hand, so citation changes read as titles. */
  titles: ReadonlyMap<string, string>;
  onClose: () => void;
};

type Sourced = { sources?: { id: string; title: string }[] };

/** The default to compare with: the next older submission, or the nearest newer one when the shown one is the oldest. */
function defaultKey(shown: SubmissionOption, others: SubmissionOption[], all: SubmissionOption[]): string {
  const at = all.findIndex((o) => o.key === shown.key);
  const older = all.slice(at + 1)[0];
  return older ? older.key : others[others.length - 1].key;
}

/**
 * The step-by-step comparison of the shown submission with another one, from both artifacts.
 * Each row says in words what changed; colour only follows the words.
 * Mount it with `key={shown.key}` so the default resets when the shown submission changes.
 */
export function SubmissionDiff({ id: sectionId, kind, shown, options, titles, onClose }: SubmissionDiffProps) {
  const id = useId();
  const { client, version } = useClient();
  // The compared submission's own step views name the documents it cites; until they arrive (or if
  // they can't), its citations read from the titles on hand, or as ids.
  const [extra, setExtra] = useState<{ key: string; titles: [string, string][] } | null>(null);
  const others = options.filter((o) => o.key !== shown.key);
  const [picked, setPicked] = useState<string | null>(null);
  const withKey = others.length === 0 ? null
    : picked && others.some((o) => o.key === picked) ? picked : defaultKey(shown, others, options);
  const compared = others.find((o) => o.key === withKey);
  const comparedOrder = compared?.record.order.id ?? null;
  const comparedNumber = compared?.submission.number ?? null;

  useEffect(() => {
    if (kind !== "procedure" || comparedOrder === null || comparedNumber === null) return;
    const key = `${comparedOrder}#${comparedNumber}`;
    let live = true;
    client.getSubmissionView(comparedOrder, comparedNumber).then(
      (view) => {
        const pairs = (view.steps as Sourced[]).flatMap((s) => (s.sources ?? []).map((d) => [d.id, d.title] as [string, string]));
        if (live) setExtra({ key, titles: pairs });
      },
      () => {},
    );
    return () => { live = false; };
  }, [client, kind, comparedOrder, comparedNumber, version]);

  const extraKey = withKey;
  const lookup = useMemo(() => {
    const map = new Map(titles);
    if (extra && extra.key === extraKey) for (const [docId, title] of extra.titles) if (!map.has(docId)) map.set(docId, title);
    return map;
  }, [titles, extra, extraKey]);

  if (others.length === 0 || withKey === null) return null;
  const before = others.find((o) => o.key === withKey)!;
  const result = diffRows(kind, before.submission, shown.submission, lookup);
  const rows = result.readable ? result.rows : [];
  const changed = rows.some((r) => r.change !== "unchanged");

  return (
    <section id={sectionId} className="hist-diff" aria-labelledby={`${id}-title`}>
      <div className="hist-diff-head">
        <h3 id={`${id}-title`} className="hist-diff-title">
          Comparing {shown.record.order.id} submission {shown.submission.number}
        </h3>
        <button type="button" className="ws-button hist-quiet" onClick={onClose}>Close comparison</button>
      </div>
      <span className="hist-field">
        <label htmlFor={`${id}-with`} className="hist-label">Compare with</label>
        <select id={`${id}-with`} className="hist-select" value={withKey} onChange={(e) => setPicked(e.target.value)}>
          {others.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </span>
      {!result.readable && result.unreadable.map((side) => (
        <p key={`${side.workOrderId}#${side.number}`} className="hist-diff-unreadable">{unreadableLine(side)}</p>
      ))}
      {result.readable && !changed && <p className="hist-diff-same">The steps are the same.</p>}
      {result.readable && <ol className="hist-diff-rows" aria-label="Changes">
        {rows.map((row, i) => row.change === "unchanged" ? (
          <li key={`unchanged-${i}`} className="hist-diff-row" data-change="unchanged">{row.mark}</li>
        ) : (
          <li key={`${row.change}-${row.step}-${i}`} className="hist-diff-row" data-change={row.change}>
            <span className="hist-diff-mark">{row.mark}</span>
            {row.change === "changed" && row.details.length > 0 && (
              <ul className="hist-diff-details" aria-label="What changed">
                {row.details.map((line, j) => <li key={j}>{line}</li>)}
              </ul>
            )}
            <span className="hist-diff-step">{row.step}</span>
            <span className="hist-diff-text">{row.text}</span>
          </li>
        ))}
      </ol>}
    </section>
  );
}
