"use client";

import { useId, useState } from "react";

import { diffRows, unreadableLine } from "../lib/history.ts";
import type { SubmissionOption } from "../lib/history.ts";

export type SubmissionDiffProps = {
  /** The section's id, for the Compare button's `aria-controls`. */
  id: string;
  kind: "procedure" | "run_plan";
  /** The shown submission: the "after" side. */
  shown: SubmissionOption;
  /** Every submission, newest first; all but the shown one can be compared with it. */
  options: SubmissionOption[];
  onClose: () => void;
};

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
export function SubmissionDiff({ id: sectionId, kind, shown, options, onClose }: SubmissionDiffProps) {
  const id = useId();
  const others = options.filter((o) => o.key !== shown.key);
  const [picked, setPicked] = useState<string | null>(null);
  if (others.length === 0) return null;
  const withKey = picked && others.some((o) => o.key === picked) ? picked : defaultKey(shown, others, options);
  const before = others.find((o) => o.key === withKey)!;
  const result = diffRows(kind, before.submission, shown.submission);
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
            <span className="hist-diff-step">{row.step}</span>
            <span className="hist-diff-text">{row.text}</span>
          </li>
        ))}
      </ol>}
    </section>
  );
}
